"""Regression tests for CL2X-298's compiler/AgentCut cut contract."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.cut_motivation_gate import required_cut_metadata
from tools.edit_plan_adapter import from_ordered_edl


ROOT = Path(__file__).resolve().parents[2]
AGENTCUT_SOURCE = (
    Path("/Users/rogerwu/Documents/Codex/2026-07-17/")
    / "referenced-chatgpt-conversation-this-is-untrusted-2/agentcut-0.7.0"
)


def contract(reason="NEW_INFORMATION"):
    return {
        "cut_reason": reason,
        "scene_id": "courtyard",
        "light_key": "night_lantern",
        "axis_line": "A1",
        "eyeline": "RIGHT",
        "new_information": "红玉吊坠露出缺口",
    }


class CompilerContractTest(unittest.TestCase):
    def test_required_metadata_is_explicit_and_closed(self):
        result = required_cut_metadata(contract(), label="fixture")
        self.assertEqual(result["cut_reason"], "NEW_INFORMATION")
        with self.assertRaisesRegex(ValueError, "cut_reason"):
            required_cut_metadata({**contract(), "cut_reason": None}, label="fixture")
        with self.assertRaisesRegex(ValueError, "continuity"):
            required_cut_metadata({k: v for k, v in contract().items() if k != "eyeline"}, label="fixture")

    def test_ordered_edl_preserves_explicit_contract_and_unknown_fields(self):
        segment = {
            "dialogue_id": "D01",
            "a_source_id": "D01",
            "a_video_path": "a.mp4",
            "target_duration": 2.0,
            **contract("SPEAKER_CHANGE"),
            "b_insert": {
                "source_id": "B01",
                "video_path": "b.mp4",
                "duration": 0.5,
                "counted_duration_estimate": 0.4,
                "placement": "AFTER_LINE",
                "listener": "陈迹",
                **contract("NEW_INFORMATION"),
                "coverage_group": "B",
            },
        }
        project = from_ordered_edl({"segments": [segment]})
        clips = project["timeline"]["videoTracks"][0]["clips"]
        self.assertTrue(project["requireCutReason"])
        self.assertEqual(clips[1]["metadata"]["cut_reason"], "NEW_INFORMATION")
        self.assertEqual(clips[1]["metadata"]["coverage_group"], "B")

    def test_ordered_edl_does_not_invent_missing_reason(self):
        segment = {
            "dialogue_id": "D01",
            "a_source_id": "D01",
            "a_video_path": "a.mp4",
            "target_duration": 2.0,
            **{k: v for k, v in contract().items() if k != "cut_reason"},
        }
        with self.assertRaisesRegex(ValueError, "cut_reason"):
            from_ordered_edl({"segments": [segment]})


@unittest.skipUnless(AGENTCUT_SOURCE.is_dir(), "AgentCut source artifact is unavailable")
class AgentCutContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(AGENTCUT_SOURCE))
        from agentcut.models import Project  # noqa: PLC0415
        from agentcut.validation import validate_cut_reason_contract  # noqa: PLC0415
        cls.Project = Project
        cls.validate_cut_reason_contract = staticmethod(validate_cut_reason_contract)

    def test_unknown_metadata_is_preserved_and_switch_parses(self):
        project = self.Project.parse({
            "version": "1.0",
            "output": {"path": "/tmp/test.mp4"},
            "timeline": {"videoTracks": [{"id": "v", "clips": [{
                "id": "c1", "source": "/tmp/source.mp4", "start": 0, "in": 0, "duration": 1,
                "metadata": {**contract(), "coverage_group": "A", "new_information": "x"},
            }]}]},
            "requireCutReason": True,
        })
        self.assertTrue(project.require_cut_reason)
        self.assertEqual(project.video_tracks[0].clips[0].metadata["coverage_group"], "A")

    def test_strict_switch_reports_each_cut_reason(self):
        clip = SimpleNamespace(id="c1", metadata={"cut_reason": "NEW_INFORMATION"}, source="x", start=0, duration=1)
        track = SimpleNamespace(id="v", enabled=True, clips=(clip,))
        issues, report = self.validate_cut_reason_contract(SimpleNamespace(require_cut_reason=True, video_tracks=(track,)))
        self.assertEqual(len(report["cuts"]), 1)
        self.assertIn("scene_id", report["missing"][0]["missingFields"])
        self.assertTrue(any(issue.code == "CUT_REASON_REQUIRED" for issue in issues))


if __name__ == "__main__":
    unittest.main()
