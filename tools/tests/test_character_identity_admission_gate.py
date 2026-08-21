import hashlib
import math
import unittest
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
    },
}


class FakeBackend:
    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, path):
        return self.vectors[path.name]


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


if __name__ == "__main__":
    unittest.main()
