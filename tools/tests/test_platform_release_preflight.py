import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.platform_release_preflight import evaluate_release_preflight


class PlatformReleasePreflightTests(unittest.TestCase):
    def _write_verified_final(self, root: Path, *, tamper: bool = False) -> dict:
        final = root / "final.mp4"
        final.write_bytes(b"verified-final")
        digest = hashlib.sha256(final.read_bytes()).hexdigest()
        qa = root / "qa.json"
        qa.write_text(
            json.dumps({"status": "PASS_FINAL_LOCK", "final_sha256": digest}),
            encoding="utf-8",
        )
        lock = root / "lock.json"
        lock.write_text(
            json.dumps(
                {
                    "status": "FINAL_LOCKED_RELEASE_HOLD",
                    "final": str(final),
                    "qa_freeze": str(qa),
                    "sha256": digest,
                }
            ),
            encoding="utf-8",
        )
        if tamper:
            final.write_bytes(b"tampered")
        return {
            "episode": "E21",
            "stage": "FINAL_LOCKED_S3_DELIVERED_RELEASE_HOLD",
            "status": "STOPPED_HARD_RELEASE_HOLD",
            "active_evidence": str(lock),
        }

    def test_exact_block_entry_fails_closed(self):
        result = evaluate_release_preflight(
            "E21",
            {
                "schedule_gate": {
                    "directive": "CL2X-349",
                    "release_blocked_episodes": ["E21"],
                }
            },
        )
        self.assertFalse(result["release_allowed"])
        self.assertEqual(result["status"], "HARD_HOLD")
        self.assertIn("episode_listed_in_release_blocked_episodes", result["reasons"])

    def test_versioned_block_entry_fails_closed(self):
        result = evaluate_release_preflight(
            "E23",
            {
                "schedule_gate": {
                    "directive": "CL2X-349",
                    "release_blocked_episodes": ["E23_CURRENT_V12"],
                }
            },
        )
        self.assertFalse(result["release_allowed"])

    def test_held_line_fails_closed_without_block_list(self):
        result = evaluate_release_preflight(
            "E22",
            {
                "schedule_gate": {"directive": "CL2X-349"},
                "lines": {"slot": {"episode": "E22", "status": "HOLD_PENDING_REWORK"}},
            },
        )
        self.assertFalse(result["release_allowed"])
        self.assertIn("episode_line_is_held_or_stopped", result["reasons"])

    def test_unblocked_active_episode_passes(self):
        result = evaluate_release_preflight(
            "E24",
            {
                "schedule_gate": {
                    "directive": "CL2X-349",
                    "release_blocked_episodes": ["E21", "E22"],
                },
                "lines": {"slot": {"episode": "E24", "status": "ACTIVE_RENDER"}},
            },
        )
        self.assertTrue(result["release_allowed"])
        self.assertEqual(result["status"], "PASS")

    def test_verified_final_lock_can_pass_stopped_release_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            line = self._write_verified_final(root)
            result = evaluate_release_preflight(
                "E21", {"lines": {"slot": line}}, root=root
            )
        self.assertTrue(result["release_allowed"])
        self.assertEqual(result["verified_final_locks"][0]["reason"], "verified_final_lock")

    def test_tampered_final_remains_hard_held(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            line = self._write_verified_final(root, tamper=True)
            result = evaluate_release_preflight(
                "E21", {"lines": {"slot": line}}, root=root
            )
        self.assertFalse(result["release_allowed"])
        self.assertIn("episode_line_is_held_or_stopped", result["reasons"])

    def test_e37_requires_render_bound_subtitles_and_outro(self):
        result = evaluate_release_preflight(
            "E37",
            {"lines": {"slot": {"episode": "E37", "status": "ACTIVE_RELEASE"}}},
        )
        self.assertFalse(result["release_allowed"])
        self.assertIn("release_branding_render_gate_not_verified", result["reasons"])

    def test_e37_verified_release_branding_can_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            final = root / "final.mp4"
            final.write_bytes(b"branded-final")
            digest = hashlib.sha256(final.read_bytes()).hexdigest()
            gate = root / "branding.json"
            gate.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "hard_gate_passed": True,
                        "final_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            result = evaluate_release_preflight(
                "E37",
                {
                    "lines": {
                        "slot": {
                            "episode": "E37",
                            "status": "ACTIVE_RELEASE",
                            "production_master": str(final),
                            "latest_release_branding_render_gate": str(gate),
                        }
                    }
                },
                root=root,
            )
        self.assertTrue(result["release_allowed"])
        self.assertEqual(
            result["release_branding_checks"][0]["reason"],
            "verified_release_branding_render_gate",
        )

    def test_e45_requires_real_media_boundary_acceptance(self):
        result = evaluate_release_preflight(
            "E45", {"lines": {"slot": {"episode": "E45", "status": "ACTIVE_RELEASE"}}}
        )
        self.assertFalse(result["release_allowed"])
        self.assertIn("media_boundary_acceptance_not_verified", result["reasons"])

    def test_e45_accepts_complete_boundary_report_when_other_gates_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            final = root / "final.mp4"
            final.write_bytes(b"branded-final")
            digest = hashlib.sha256(final.read_bytes()).hexdigest()
            branding = root / "branding.json"
            branding.write_text(json.dumps({
                "status": "PASS", "hard_gate_passed": True, "final_sha256": digest,
            }), encoding="utf-8")
            boundary = root / "boundary.json"
            boundary.write_text(json.dumps({
                "schema": "qingshan.media_boundary_acceptance.v1_safe_cut_and_real_transition",
                "status": "PASS", "boundary_count": 1, "failures": [],
                "rows": [{"boundary_id": "B1", "status": "PASS", "failures": []}],
            }), encoding="utf-8")
            result = evaluate_release_preflight("E45", {"lines": {"slot": {
                "episode": "E45", "status": "ACTIVE_RELEASE",
                "production_master": str(final),
                "latest_release_branding_render_gate": str(branding),
                "media_boundary_acceptance": str(boundary),
            }}}, root=root)
        self.assertTrue(result["release_allowed"])


if __name__ == "__main__":
    unittest.main()
