import hashlib

import pytest

from tools.seedance2_prompt_compiler import compile_prompt


def frame(path, timestamp, state, zone="room", transition=None):
    path.write_bytes(f"frame-{timestamp}".encode())
    row = {
        "timestamp_seconds": timestamp,
        "image_path": str(path),
        "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "state_token": state,
        "location_zone": zone,
        "actor_blocking": f"blocking-{state}",
        "action_event": f"event-{state}",
        "reference_role": f"state-{state}",
        "camera_side": zone,
        "camera_position": "fixed three-quarter position",
        "camera_facing": "toward the same breach",
        "preserve_from_previous": "identity, location and action axis",
        "do_not_inherit": ["text", "watermark"],
    }
    if transition is not None:
        row["transition_from_previous"] = transition
    return row


def transition(kind="CONTINUOUS_ACTION"):
    return {
        "kind": kind,
        "teleport_allowed": False,
        "action_reset_allowed": False,
        "continuous_camera_path": "locked axis",
        "camera_axis_reset_allowed": False,
        "camera_from_side": "room",
        "camera_to_side": "room",
        "camera_travel_distance_m": 0,
        "camera_axis_change_degrees": 0,
    }


def spec(keyframes):
    return {
        "mode": "multi_keyframe_long_take",
        "duration_seconds": 15,
        "model": "seedance-2.0-pro",
        "resolution": "1080p",
        "real_time_1x": True,
        "camera_motion_policy": "MOTIVATED_TRACK_OR_LOCKED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM",
        "subject_and_identity_lock": "同一人物、服装和伤痕",
        "spatial_continuity_lock": "同一房间和同一墙洞",
        "action_axis": "护账逃生",
        "negative_constraints": ["慢动作", "动作重演"],
        "keyframes": keyframes,
    }


def test_compiles_ordered_multi_keyframe_long_take(tmp_path):
    crossing = transition("SAME_APERTURE_CROSSING")
    crossing.update({
        "aperture_id": "east-wall-breach", "direction": "inside_to_outside",
        "camera_path_kind": "FOLLOW_THROUGH_SAME_APERTURE",
        "camera_crosses_with_subjects": True,
        "camera_path_aperture_id": "east-wall-breach",
        "camera_from_side": "room", "camera_to_side": "street",
        "camera_travel_distance_m": 2, "camera_axis_change_degrees": 10,
    })
    keyframes = [
        frame(tmp_path / "a.png", 0, "inside_start"),
        frame(tmp_path / "b.png", 7, "at_breach", transition=transition()),
        frame(tmp_path / "c.png", 15, "outside_landing", zone="street", transition=crossing),
    ]
    prompt, manifest = compile_prompt(spec(keyframes))
    assert manifest["route"] == "/api/v1/generation/omni-video"
    assert [row["reference"] for row in manifest["keyframes"]] == ["@图片1", "@图片2", "@图片3"]
    assert "15秒到达@图片3" in prompt
    assert "smooth roam" in prompt
    assert "LORA-SD2-001-REFERENCE-GEOMETRY-LEAK" in prompt
    assert {
        "LORA-SD2-001-REFERENCE-GEOMETRY-LEAK",
        "LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION",
        "LORA-SD2-003-ADJACENT-CAMERA-TRAJECTORY",
    }.issubset(set(manifest["local_lora_memory"]["applied_sample_ids"]))


def test_rejects_impossible_camera_axis_jump(tmp_path):
    bad = transition()
    bad["camera_axis_change_degrees"] = 180
    keyframes = [
        frame(tmp_path / "a.png", 0, "start"),
        frame(tmp_path / "b.png", 7, "middle", transition=bad),
        frame(tmp_path / "c.png", 15, "done", transition=transition()),
    ]
    with pytest.raises(ValueError, match="camera axis change exceeds 90 degrees"):
        compile_prompt(spec(keyframes))


def test_rejects_location_jump_without_same_aperture(tmp_path):
    keyframes = [
        frame(tmp_path / "a.png", 0, "inside_start"),
        frame(tmp_path / "b.png", 7, "at_breach", transition=transition()),
        frame(tmp_path / "c.png", 15, "outside_landing", zone="street", transition=transition()),
    ]
    with pytest.raises(ValueError, match="SAME_APERTURE_CROSSING"):
        compile_prompt(spec(keyframes))


def test_rejects_repeated_action_state(tmp_path):
    keyframes = [
        frame(tmp_path / "a.png", 0, "same"),
        frame(tmp_path / "b.png", 7, "same", transition=transition()),
        frame(tmp_path / "c.png", 15, "done", transition=transition()),
    ]
    with pytest.raises(ValueError, match="repeats action state"):
        compile_prompt(spec(keyframes))


def test_rejects_non_pro_or_non_1080p(tmp_path):
    keyframes = [
        frame(tmp_path / "a.png", 0, "start"),
        frame(tmp_path / "b.png", 7, "middle", transition=transition()),
        frame(tmp_path / "c.png", 15, "done", transition=transition()),
    ]
    candidate = spec(keyframes)
    candidate["model"] = "seedance-2.0-fast"
    with pytest.raises(ValueError, match="seedance-2.0-pro"):
        compile_prompt(candidate)
