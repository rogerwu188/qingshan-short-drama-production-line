import unittest

from tools.keyframe_output_identity_gate import evaluate


class KeyframeOutputIdentityGateTest(unittest.TestCase):
    def task(self):
        return {
            "shot_id": "E47-S08-04",
            "identity_reference_transport": {
                "transport_guarantee": "SOFT_REFERENCE_REQUIRES_EXACT_OUTPUT_GATE",
                "authority_map": {"CHAR-CHENJI": "@图片5", "CHAR-SICAO": "@图片6"},
            },
        }

    def test_declared_but_unexecuted_identity_gate_fails(self):
        result = evaluate([self.task()], [{"shot_id": "E47-S08-04", "sha256": "out"}], [])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(len(result["failures"]), 2)

    def test_exact_output_sha_and_per_entity_evidence_pass(self):
        rows = [{
            "shot_id": "E47-S08-04", "entity_id": entity,
            "method": "INSIGHTFACE_COSINE_V1", "output_sha256": "out",
            "threshold_pass": True, "status": "PASS",
        } for entity in ("CHAR-CHENJI", "CHAR-SICAO")]
        result = evaluate([self.task()], [{"shot_id": "E47-S08-04", "sha256": "out"}], rows)
        self.assertEqual(result["status"], "PASS", result["failures"])


if __name__ == "__main__":
    unittest.main()
