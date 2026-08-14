#!/usr/bin/env python3
"""Project-agnostic smoke tests for the portable cut-motivation gate."""

import unittest

from tools.cut_motivation_gate import evaluate


def clip(index, start, *, reason=None, dialogue=None, new_information=None):
    metadata = {
        "shot_index": index,
        "dialogue_id": dialogue,
        "scene_id": "SCENE_01",
        "light_key": "DAY_SOFT",
        "axis_line": "AXIS_A",
        "eyeline": "LEFT" if index % 2 == 0 else "RIGHT",
    }
    if reason:
        metadata["cut_reason"] = reason
    if reason == "SPEAKER_CHANGE":
        metadata["speaker"] = f"SPEAKER_{index}"
    if reason == "NEW_INFORMATION":
        metadata["new_information"] = (
            "The new clue becomes visible."
            if new_information is None
            else new_information
        )
    return {
        "id": f"CLIP_{index}",
        "start": float(start),
        "duration": 2.0,
        "source": f"SOURCE_{index}.mp4",
        "metadata": metadata,
    }


def project(clips):
    return {"timeline": {"videoTracks": [{"clips": clips}]}}


class PortableCutMotivationTests(unittest.TestCase):
    def test_evidence_backed_speaker_change_passes(self):
        result = evaluate(
            project(
                [
                    clip(0, 0.0, dialogue="DIA_01"),
                    clip(1, 2.0, reason="SPEAKER_CHANGE", dialogue="DIA_02"),
                ]
            )
        )
        self.assertEqual(result["gate_status"], "PASS")

    def test_unmotivated_cut_blocks(self):
        result = evaluate(project([clip(0, 0.0), clip(1, 2.0)]))
        self.assertEqual(result["gate_status"], "REJECT_RECUT")

    def test_insert_without_new_information_blocks(self):
        result = evaluate(
            project(
                [
                    clip(0, 0.0, dialogue="DIA_01"),
                    clip(1, 2.0, reason="NEW_INFORMATION", new_information=""),
                ]
            )
        )
        self.assertEqual(result["gate_status"], "REJECT_RECUT")


if __name__ == "__main__":
    unittest.main()
