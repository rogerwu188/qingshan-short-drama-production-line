"""An offscreen-only speaker needs no identity anchor at video preflight (field E11-VU-005, device 1101,
2026-11-15: MISSING_ANCHOR_FOR_CANONICAL_ENTITY:missing=CHAR-XUANMENSISTER on an object insert)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_nalu_preproduction as pre  # noqa: E402
from tools.shot_media_admission_gate import precheck_submission_inputs  # noqa: E402

SISTER = "CHAR-XUANMENSISTER"
OFFSCREEN = {"character": "玄门宗师妹", "character_id": SISTER, "face_visibility": "OFFSCREEN_VOICE_ONLY"}
VISIBLE = {"character": "孟子秋", "character_id": "CHAR-MENGZIQIU", "face_visibility": "VISIBLE_PER_FRAME_CONTENT"}


def task(exempt: list[str]) -> dict:
    """The shape finalize_video_tasks leaves for an object insert with an offscreen line."""
    row = {"character_id": SISTER, "screen_slot": "OFFSCREEN", "map_presence": "OFFSCREEN_VOICE_ONLY"}
    result = {
        "media_stage": "VIDEO",
        "canonical_characters": [],
        "canonical_props": ["PROP-SWORD"],
        "reference_image_sequence": [{"entity_id": "PROP-SWORD", "role": "PROP_REFERENCE", "path": "sword.png"}],
        "blocking": {"characters": [dict(row)], "props": [{"prop_id": "PROP-SWORD"}]},
        "action_end_blocking": {"characters": [dict(row)], "props": [{"prop_id": "PROP-SWORD"}]},
    }
    if exempt:
        result["identity_authority_exempt_character_ids"] = exempt
    return result


class OffscreenSpeakerVideoAnchorExemptTest(unittest.TestCase):
    def test_only_a_speaker_no_shot_shows_is_offscreen_only(self) -> None:
        self.assertEqual(pre.offscreen_only_speaker_ids([{"cast": [OFFSCREEN]}]), [SISTER])
        self.assertEqual(pre.offscreen_only_speaker_ids([{"cast": [VISIBLE, OFFSCREEN]}]), [SISTER])
        self.assertEqual(pre.offscreen_only_speaker_ids([{"cast": [VISIBLE]}]), [])
        self.assertEqual(pre.offscreen_only_speaker_ids([]), [])

    def test_heard_in_one_shot_and_shown_in_another_keeps_identity_authority(self) -> None:
        shown = {"character": "玄门宗师妹", "character_id": SISTER}
        self.assertEqual(pre.offscreen_only_speaker_ids([{"cast": [OFFSCREEN]}, {"cast": [shown]}]), [])

    def test_name_only_row_resolves_through_the_contract(self) -> None:
        row = {"character": "玄门宗师妹", "face_visibility": "OFFSCREEN_VOICE_ONLY"}
        self.assertEqual(pre.offscreen_only_speaker_ids([{"cast": [row]}], {"玄门宗师妹": SISTER}), [SISTER])

    def test_gate_no_longer_wants_an_anchor_for_her(self) -> None:
        before = precheck_submission_inputs(task([]), enforce=True, root=ROOT)
        self.assertIn(SISTER, before.get("missing_characters") or [])
        after = precheck_submission_inputs(task([SISTER]), enforce=True, root=ROOT)
        self.assertEqual(after.get("missing_characters") or [], [])
        self.assertNotEqual(after.get("failure_code"), "MISSING_ANCHOR_FOR_CANONICAL_ENTITY")

    def test_finalize_declares_the_exemption(self) -> None:
        src = (TOOLS / "build_nalu_preproduction.py").read_text(encoding="utf-8")
        body = src.split("def finalize_video_tasks(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("offscreen_only_speaker_ids(specs, name2char)", body)
        self.assertIn("sorted(set(never_face_ids) | set(offscreen_speaker_ids))", body)


if __name__ == "__main__":
    unittest.main()
