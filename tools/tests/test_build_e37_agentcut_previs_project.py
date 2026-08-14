import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "configs/e37_agentcut_previs_replacement_project_v1_20260802.json"


class E37AgentCutPrevisProjectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = json.loads(PROJECT.read_text(encoding="utf-8"))
        cls.clips = cls.project["timeline"]["videoTracks"][0]["clips"]

    def test_previs_is_never_release_eligible(self):
        self.assertFalse(self.project["releaseProject"])
        self.assertFalse(self.project["qingshanAudit"]["releaseEligible"])
        self.assertIn("NOT_PRODUCTION_VIDEO", self.project["metadata"]["hard_scope_limit"])

    def test_all_replacement_slots_are_contiguous(self):
        self.assertEqual(len(self.clips), 22)
        self.assertEqual(self.clips[0]["start"], 0.0)
        self.assertEqual(self.clips[-1]["start"] + self.clips[-1]["duration"], 174.0)
        for left, right in zip(self.clips, self.clips[1:]):
            self.assertEqual(left["start"] + left["duration"], right["start"])

    def test_scoring_and_hard_fail_policy_are_bound(self):
        registry = self.project["metadata"]["replacement_registry"]
        self.assertEqual({row["pass_score"] for row in registry}, {60, 80})
        self.assertTrue(all(row["expected_candidate_sha256"] is None for row in registry))
        self.assertTrue(all("IDENTITY" in row["hard_fail_overrides_score"] for row in registry))

    def test_every_clip_has_recipe_provenance_and_replacement_gate(self):
        for clip in self.clips:
            metadata = clip["metadata"]
            self.assertTrue(metadata["replacement_required"])
            self.assertEqual(metadata["shot_recipe"]["version"], "1.0.0")
            phases = metadata["shot_recipe"]["override"]["motion_arc"]["phases"]
            self.assertEqual([row["phase_id"] for row in phases][0:2], ["setup", "contact"])
            self.assertEqual(phases[-1]["phase_id"], "result")
            self.assertEqual(len(metadata["previs_source_sha256"]), 64)
            self.assertEqual(len(metadata["prompt_sha256"]), 64)
            self.assertIn("PASS_PREVIS_SCOPE_ONLY", metadata["source_qa"])


if __name__ == "__main__":
    unittest.main()
