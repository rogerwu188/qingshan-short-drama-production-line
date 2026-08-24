import hashlib
import math
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.character_identity_admission_gate import evaluate


REGISTRY = {
    "characters": {"CHAR-A": {"status": "LOCKED_RETURNING"}},
    "parameters": {
        "canonical_views_min": 3,
        "sample_frames_per_source_min": 3,
        "embedding_cosine_pass_threshold": 0.45,
        "embedding_cosine_fail_threshold": 0.30,
        "embedding_cosine_boundary_auto_decision_midpoint": 0.375,
        "boundary_human_timeout_minutes": 15,
    },
}


class FakeBackend:
    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, path):
        return self.vectors[path.name]


class MultiFaceReferenceBackend(FakeBackend):
    def embed_all(self, path):
        value = self.vectors[path.name]
        return value if value and isinstance(value[0], list) else [value]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path, sample_vector):
    references = [root / f"ref-{index}.jpg" for index in range(3)]
    samples = [root / f"sample-{index}.jpg" for index in range(3)]
    for path in references + samples:
        path.write_bytes(path.name.encode())
    row = {
        "character_id": "CHAR-A",
        "canonical_reference_paths": [str(path) for path in references],
        "canonical_reference_sha256": {str(path): sha(path) for path in references},
        "sample_frame_paths": [str(path) for path in samples],
        "sample_frame_sha256": {str(path): sha(path) for path in samples},
    }
    vectors = {path.name: [1.0, 0.0] for path in references}
    vectors.update({path.name: sample_vector for path in samples})
    return {"sources": [{"source_id": "S1", "characters": [row]}]}, FakeBackend(vectors)


class CharacterIdentityAdmissionGateTests(unittest.TestCase):
    def test_strong_embedding_pass_needs_no_human(self):
        with TemporaryDirectory() as directory:
            manifest, backend = fixture(Path(directory), [1.0, 0.0])
            report = evaluate(manifest, REGISTRY, backend)
            self.assertEqual(report["status"], "PASS", report["failures"])
            self.assertEqual(report["reviewer_type"], "AI_VISUAL")

    def test_boundary_band_requires_human_arbitration(self):
        with TemporaryDirectory() as directory:
            manifest, backend = fixture(Path(directory), [0.4, math.sqrt(0.84)])
            report = evaluate(manifest, REGISTRY, backend)
            self.assertEqual(report["status"], "BOUNDARY_REQUIRES_HUMAN")
            self.assertFalse(report["boundary_auto_resolved_after_timeout"])

    def test_boundary_timeout_nearer_pass_admits_best_effort_as_p2(self):
        with TemporaryDirectory() as directory:
            manifest, backend = fixture(Path(directory), [0.4, math.sqrt(0.84)])
            manifest["boundary_human_review_requested_at"] = "2026-08-21T00:00:00Z"
            report = evaluate(
                manifest, REGISTRY, backend,
                now_utc=datetime(2026, 8, 21, 0, 16, tzinfo=timezone.utc),
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["admission_tier"], "ADMITTED_WITH_P2")
            self.assertTrue(report["boundary_auto_resolved_after_timeout"])
            self.assertEqual(report["boundary_auto_resolution_directions"], ["ADMIT_BEST_EFFORT"])

    def test_boundary_timeout_nearer_fail_switches_coverage(self):
        with TemporaryDirectory() as directory:
            manifest, backend = fixture(Path(directory), [0.34, math.sqrt(1 - 0.34 ** 2)])
            manifest["boundary_human_review_requested_at"] = "2026-08-21T00:00:00Z"
            report = evaluate(
                manifest, REGISTRY, backend,
                now_utc=datetime(2026, 8, 21, 0, 16, tzinfo=timezone.utc),
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(report["boundary_auto_resolved_after_timeout"])
            self.assertEqual(report["boundary_auto_resolution_directions"], ["SWITCH_COVERAGE"])
            self.assertAlmostEqual(
                report["objective_verification"]["decisions"][0]["aggregate_median"], 0.34
            )

    def test_low_embedding_fails_objectively(self):
        with TemporaryDirectory() as directory:
            manifest, backend = fixture(Path(directory), [0.2, math.sqrt(0.96)])
            report = evaluate(manifest, REGISTRY, backend)
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any("below_fail_threshold" in item for item in report["failures"]))

    def test_exact_sha_binding_is_required(self):
        with TemporaryDirectory() as directory:
            manifest, backend = fixture(Path(directory), [1.0, 0.0])
            manifest["sources"][0]["characters"][0]["sample_frame_sha256"] = {}
            report = evaluate(manifest, REGISTRY, backend)
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any("sample_frame_sha_missing" in item for item in report["failures"]))

    def test_unregistered_character_fails(self):
        with TemporaryDirectory() as directory:
            manifest, backend = fixture(Path(directory), [1.0, 0.0])
            manifest["sources"][0]["characters"][0]["character_id"] = "CHAR-MISSING"
            report = evaluate(manifest, REGISTRY, backend)
            self.assertTrue(any("character_not_registered" in item for item in report["failures"]))

    def test_designated_multiview_card_may_supply_multiple_reference_faces(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            card = root / "three-view-card.png"
            card.write_bytes(b"card")
            samples = [root / f"sample-{index}.jpg" for index in range(3)]
            for path in samples:
                path.write_bytes(path.name.encode())
            row = {
                "character_id": "CHAR-A",
                "canonical_view_count": 3,
                "canonical_reference_paths": [str(card)],
                "canonical_reference_sha256": {str(card): sha(card)},
                "sample_frame_paths": [str(path) for path in samples],
                "sample_frame_sha256": {str(path): sha(path) for path in samples},
            }
            vectors = {card.name: [[1.0, 0.0], [0.98, 0.02]]}
            vectors.update({path.name: [1.0, 0.0] for path in samples})
            report = evaluate(
                {"sources": [{"source_id": "S1", "characters": [row]}]},
                REGISTRY,
                MultiFaceReferenceBackend(vectors),
            )
            self.assertEqual(report["status"], "PASS", report["failures"])
            decision = report["objective_verification"]["decisions"][0]
            self.assertEqual(decision["canonical_view_count"], 3)
            self.assertEqual(decision["canonical_face_embedding_count"], 2)


if __name__ == "__main__":
    unittest.main()
