import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.event_boundary_continuity_contract import POLICY
from tools.opening_anchor_chain_gate import validate_opening_anchor_chain


def _state_contract():
    person = {
        "presence": "VISIBLE",
        "posture": "SEATED",
        "injury": "UNCHANGED",
        "wardrobe": "LOCKED",
        "position": "LOCKED_MAP_POSITION",
    }
    environment = {
        "time": "MORNING",
        "weather": "CLEAR_DRY",
        "lighting": "NATURAL_EASTERN_DAYLIGHT",
        "space_topology": "LOCKED_MAP",
        "population": "CURRENT_SHOT_CAST_ONLY",
        "ambient_life": "MOTIVATED_MICROMOTION",
    }
    return {
        "schema": "qingshan.persistent_state_contract.v1",
        "status": "PASS",
        "tracked_character_ids": ["CHAR-A"],
        "characters": [{
            "character_id": "CHAR-A",
            "entry_state": dict(person),
            "exit_state": dict(person),
        }],
        "environment": {
            "entry_state": dict(environment),
            "exit_state": dict(environment),
        },
        "authorized_boundary_changes": [],
    }


def _task(tmp_path):
    opening = tmp_path / "opening.png"
    opening.write_bytes(b"opening")
    source = tmp_path / "transition.json"
    source.write_text("{}", encoding="utf-8")
    opening_sha = hashlib.sha256(opening.read_bytes()).hexdigest()
    admission = tmp_path / "admission.json"
    admission.write_text(json.dumps({
        "status": "ADMITTED",
        "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
        "asset_path": str(opening),
        "asset_sha256": opening_sha,
        "exact_sha_verified": True,
        "population_scope_verification": {
            "status": "PASS",
            "reviewed_asset_sha256": opening_sha,
            "observed_background_population_count": 0,
            "observed_unbound_living_entity_count": 0,
        },
    }), encoding="utf-8")
    persistent = _state_contract()
    return {
        "episode": "E56",
        "unit_id": "E56-VU-009-S04-06",
        "semantic_video_unit": True,
        "reference_images": [str(opening)],
        "reference_sha256": [opening_sha],
        "start_frame_admission_ref": str(admission),
        "start_frame_semantic_contract": {
            "reference_path": str(opening),
            "reference_sha256": opening_sha,
        },
        "editorial_shot_ids": ["E56-S04-06"],
        "internal_transition_contracts": [],
        "persistent_state_contract": persistent,
        "shot_state_contracts": [{
            "shot_id": "E56-S04-06",
            "persistent_state_contract": persistent,
            "camera_state": {
                "shot_scale": "MEDIUM",
                "camera_position_id": "ANGLE-2",
                "axis_id": "AXIS-1",
                "lens_intent": "50MM",
                "motion_family": "STATIC_REACTION",
            },
        }],
        "event_boundary_decision": {
            "schema": "qingshan.event_boundary_decision.v1",
            "status": "PASS",
            "boundary_class": "MOTIVATED_CUT",
            "opening_source": "CONTINUITY_DERIVED_KEYFRAME",
            "previous_unit_id": "E56-VU-009-S04-05",
            "same_continuous_event": True,
            "camera_transition": {
                "change_required": True,
                "mode": "STATE_PRESERVING_MOTIVATED_CUT",
                "state_inheritance_survives_camera_change": True,
            },
            "failures": [],
        },
        "opening_anchor_contract": {
            "policy": POLICY,
            "source": "CONTINUITY_DERIVED_KEYFRAME",
            "previous_unit_id": "E56-VU-009-S04-05",
            "materialized_path": str(opening),
            "sha256": opening_sha,
            "previous_state_reference_transport": "STRUCTURED_STATE_ONLY_NOT_PROVIDER_VISIBLE",
        },
        "continuity_state_evidence": [{
            "schema": "qingshan.structured_shot_handoff_evidence.v1",
            "status": "PASS",
            "previous_unit_id": "E56-VU-009-S04-05",
            "from_shot_id": "E56-S04-05",
            "to_shot_id": "E56-S04-06",
            "same_continuous_event": True,
            "state_inheritance_status": "PASS",
            "camera_change_reason": "authored reverse-angle speaker handoff",
            "source_ref": str(source),
            "source_ref_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }],
    }


class StructuredStateOpeningAnchorTest(unittest.TestCase):
    def test_structured_state_only_motivated_cut_passes(self):
        with tempfile.TemporaryDirectory() as value:
            self.assertEqual(validate_opening_anchor_chain(_task(Path(value))), [])

    def test_structured_state_only_requires_exact_source_evidence(self):
        with tempfile.TemporaryDirectory() as value:
            task = _task(Path(value))
            task["continuity_state_evidence"][0]["source_ref_sha256"] = "0" * 64
            failures = validate_opening_anchor_chain(task)
            self.assertIn(
                f"MOTIVATED_CUT_PREVIOUS_STATE_REFERENCE_MISSING:{task['unit_id']}",
                failures,
            )


if __name__ == "__main__":
    unittest.main()
