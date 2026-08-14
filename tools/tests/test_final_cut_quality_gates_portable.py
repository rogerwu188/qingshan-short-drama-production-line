#!/usr/bin/env python3
"""Project-agnostic smoke tests for the portable final-cut gate."""

import unittest

from tools.final_cut_quality_gates import MAX_NEAR_DUPLICATE_SHOT_PCT, evaluate


def metrics(**overrides):
    payload = {
        "schema": "qingshan.final_cut_objective_metrics.v1",
        "measured_from": "DECODED_FINAL_MP4",
        "duration_seconds": 60.0,
        "shot_count": 4,
        "sampled_shot_count": 4,
        "picture_repetition": {
            "near_duplicate_shot_pct": 0.0,
            "near_duplicate_shot_pct_non_adjacent": 0.0,
            "clusters": [],
            "non_adjacent_clusters": [],
        },
        "palette_uniformity_ADVISORY": {"dominant_cluster_pct": 30.0, "clusters": 4},
        "audio": {"digital_zero_shots": [], "level_jump_over_12db_count": 0},
    }
    payload.update(overrides)
    return payload


def report():
    return {
        "episode": "EPISODE_TEST",
        "dimensions": {
            "story": 4.0,
            "continuation": 4.0,
            "pacing": 4.0,
            "opening": 4.0,
            "clarity": 4.0,
            "visual": 4.0,
            "anti_ai": 4.0,
            "completeness": 4.0,
        },
        "problems": [],
        "evidence": {
            "burned_subtitles": True,
            "identity_color_consistent": True,
            "opening_3s_hook": True,
            "shot_notes": [
                "The lead enters while hiding a damaged letter.",
                "The witness notices the broken seal and steps back.",
                "A guard blocks the only exit and changes the balance.",
                "The letter reveals a second signature before the cut.",
            ],
        },
    }


def event_ledger():
    return {
        "events": [
            {"t": 2.0, "what": "entry"},
            {"t": 18.0, "what": "discovery"},
            {"t": 34.0, "what": "obstacle"},
            {"t": 52.0, "what": "reveal"},
        ]
    }


class PortableFinalCutGateTests(unittest.TestCase):
    def test_clean_final_artifact_passes(self):
        result = evaluate(report(), metrics(), event_ledger=event_ledger())
        self.assertEqual(result["gate_status"], "PASS")
        self.assertTrue(result["release_allowed"])

    def test_decoder_receipt_cannot_fake_viewing(self):
        payload = report()
        payload["evidence"]["playback_evidence"] = {"full_1x": "ffmpeg_decode_exit_0"}
        result = evaluate(payload, metrics(), event_ledger=event_ledger())
        self.assertEqual(result["gate_status"], "INVALID")

    def test_pixel_repetition_above_frozen_limit_blocks(self):
        repeated = metrics(
            picture_repetition={
                "near_duplicate_shot_pct": 25.0,
                "near_duplicate_shot_pct_non_adjacent": 25.0,
                "clusters": [[0, 2]],
                "non_adjacent_clusters": [[0, 2]],
            }
        )
        result = evaluate(report(), repeated, event_ledger=event_ledger())
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertEqual(MAX_NEAR_DUPLICATE_SHOT_PCT, 10.0)

    def test_missing_event_ledger_is_invalid(self):
        result = evaluate(report(), metrics(), event_ledger=None)
        self.assertEqual(result["gate_status"], "INVALID")

    def test_palette_uniformity_is_advisory(self):
        uniform = metrics(
            palette_uniformity_ADVISORY={
                "dominant_cluster_pct": 95.0,
                "status": "NOT_VALIDATED_DO_NOT_GATE_ON_THIS",
            }
        )
        result = evaluate(report(), uniform, event_ledger=event_ledger())
        self.assertEqual(result["gate_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
