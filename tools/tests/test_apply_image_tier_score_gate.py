import unittest

from tools.apply_image_tier_score_gate import bind_review_reports, tier_policy


class ImageTierPolicyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "production_policy": {
                "image_validation": {
                    "core_min_score": 80,
                    "non_core_min_score": 60,
                    "core_shot_ids": ["CORE-1"],
                }
            }
        }

    def test_core_threshold_is_80(self):
        self.assertEqual(tier_policy(self.manifest, "CORE-1"), ("CORE", 80.0))

    def test_non_core_threshold_is_60(self):
        self.assertEqual(tier_policy(self.manifest, "OTHER"), ("NON_CORE", 60.0))

    def test_review_items_bind_by_candidate_sha_not_array_position(self):
        requests = [
            {"clip_id": "A", "metadata": {"candidate_sha256": "sha-a"}},
            {"clip_id": "B", "metadata": {"candidate_sha256": "sha-b"}},
        ]
        reports = [
            {"capabilities": {"image_analysis": {"candidate_sha256": "sha-b"}}},
            {"capabilities": {"image_analysis": {"candidate_sha256": "sha-a"}}},
        ]
        bound = bind_review_reports(reports, requests)
        self.assertEqual([row[1]["capabilities"]["image_analysis"]["candidate_sha256"] for row in bound], ["sha-a", "sha-b"])

    def test_review_binding_rejects_unknown_candidate(self):
        with self.assertRaisesRegex(ValueError, "missing exact candidate SHA"):
            bind_review_reports(
                [{"capabilities": {"image_analysis": {"candidate_sha256": "wrong"}}}],
                [{"clip_id": "A", "metadata": {"candidate_sha256": "sha-a"}}],
            )


if __name__ == "__main__":
    unittest.main()
