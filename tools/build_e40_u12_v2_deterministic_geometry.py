#!/usr/bin/env python3
"""Build deterministic U12 paper-transfer geometry evidence without generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "working_assets/e40_production_20260809/u12_exact_start_frame_v1/E40_E40-U12-UNIFIED-START-FRAME-CHANGED-REPRESENTATION-V1_8c1540dc-aaf6-4bd6-83d9-1bc659a5fa08.png"
FAILED_VIDEO = ROOT / "working_assets/e40_production_20260809/u12_mouth_nonvisible_fast720_silent_visual_v1/task-001.mp4"
FINAL_QA = ROOT / "qa/e40_production_20260809/u12_mouth_nonvisible_fast720_silent_visual_v1/E40_U12_MOUTH_NONVISIBLE_FAST720_SILENT_VISUAL_FINAL_QA_V1.json"
MEMORY = ROOT / "workflow/local_lora/seedance2_prompt_failure_training.jsonl"

EXPECTED = {
    FRAME: "da04eeec8c6b89910fb222699ecc8259175dc2b0fe683a0b330437dd78023f98",
    FAILED_VIDEO: "ca2af0e8e810b75ae830dba3db06294ae9bfb21784f995baec5d60fbe016ed56",
    FINAL_QA: "5117b5aa56c9c448f792998b4de25007b4f9b5f89629c6660f9cf0e8c9764ea3",
    MEMORY: "3d093d401ff2b07d5bfe7a00dd27097105fe7aeabea44e9ccef1a7cfa8b6b60e",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def polygon_mask(shape: tuple[int, int], points: list[list[int]]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [np.asarray(points, dtype=np.int32)], 255)
    return mask


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", required=True)
    parser.add_argument("--qa-out", required=True)
    parser.add_argument("--manifest-out", required=True)
    args = parser.parse_args()

    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256(path) != expected:
            raise SystemExit(f"input SHA mismatch: {path}")

    asset_dir = ROOT / args.asset_dir
    qa_out = ROOT / args.qa_out
    manifest_out = ROOT / args.manifest_out
    asset_dir.mkdir(parents=True, exist_ok=True)

    image = cv2.imread(str(FRAME), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit("cannot decode authority frame")
    height, width = image.shape[:2]
    if (width, height) != (1008, 1792):
        raise SystemExit(f"unexpected authority dimensions: {width}x{height}")

    # Manually audited polygons at the immutable authority resolution.
    paper_polygon = [[568, 267], [593, 266], [632, 279], [779, 205], [848, 319], [770, 365], [690, 332], [641, 303]]
    curtain_polygon = [[249, 426], [1007, 415], [1007, 1247], [410, 1232], [377, 1180], [362, 810], [249, 685]]
    foreground_desk_polygon = [[409, 1214], [1007, 1224], [1007, 1328], [421, 1287]]
    mouth_roi_polygon = [[279, 593], [326, 600], [327, 692], [287, 716], [268, 659]]
    rear_rail_not_surface_polygon = [[578, 1016], [1007, 1024], [1007, 1077], [575, 1064]]

    masks = {
        "paper_mask.png": polygon_mask((height, width), paper_polygon),
        "curtain_occluder_mask.png": polygon_mask((height, width), curtain_polygon),
        "foreground_desk_plane_mask.png": polygon_mask((height, width), foreground_desk_polygon),
        "mouth_visibility_roi_mask.png": polygon_mask((height, width), mouth_roi_polygon),
        "rear_rail_not_receive_surface_mask.png": polygon_mask((height, width), rear_rail_not_surface_polygon),
    }
    for name, mask in masks.items():
        cv2.imwrite(str(asset_dir / name), mask)

    depth = np.zeros((height, width), dtype=np.uint8)
    depth[masks["rear_rail_not_receive_surface_mask.png"] > 0] = 64
    depth[masks["curtain_occluder_mask.png"] > 0] = 128
    depth[masks["foreground_desk_plane_mask.png"] > 0] = 192
    depth[masks["mouth_visibility_roi_mask.png"] > 0] = 224
    depth[masks["paper_mask.png"] > 0] = 255
    cv2.imwrite(str(asset_dir / "depth_layers.png"), depth)

    overlay = image.copy()
    colors = {
        "paper_mask.png": (0, 255, 255),
        "curtain_occluder_mask.png": (255, 128, 0),
        "foreground_desk_plane_mask.png": (0, 0, 255),
        "mouth_visibility_roi_mask.png": (255, 0, 255),
        "rear_rail_not_receive_surface_mask.png": (0, 255, 0),
    }
    for name, mask in masks.items():
        tint = np.zeros_like(overlay)
        tint[:] = colors[name]
        overlay = np.where((mask[..., None] > 0), cv2.addWeighted(overlay, 0.6, tint, 0.4, 0), overlay)
    path_points = np.asarray([[709, 285], [720, 395], [735, 650], [750, 930], [760, 1160]], dtype=np.int32)
    cv2.polylines(overlay, [path_points], False, (0, 0, 255), 8, cv2.LINE_AA)
    cv2.drawMarker(overlay, (760, 1160), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 64, 8)
    cv2.imwrite(str(asset_dir / "geometry_overlay.png"), overlay)

    paper_pixels = int(np.count_nonzero(masks["paper_mask.png"]))
    mouth_roi = image[masks["mouth_visibility_roi_mask.png"] > 0]
    mouth_stddev = float(np.std(cv2.cvtColor(mouth_roi.reshape(-1, 1, 3), cv2.COLOR_BGR2GRAY)))
    desk_curtain_overlap = int(np.count_nonzero(
        (masks["foreground_desk_plane_mask.png"] > 0) & (masks["curtain_occluder_mask.png"] > 0)
    ))

    trajectory = {
        "schema": "qingshan.e40.u12.deterministic_paper_trajectory.v1",
        "authority_resolution": [width, height],
        "status": "BLOCKED_NO_VALID_INTERIOR_RECEIVE_PLANE",
        "keyframes": [
            {"time_seconds": 0.0, "center_xy": [709, 285], "depth_layer": "FRONT_OF_CURTAIN_ABOVE_SEAM", "frame0_pixel_exact_required": True},
            {"time_seconds": 0.8, "center_xy": [720, 395], "depth_layer": "FRONT_OF_CURTAIN_AT_TOP_SEAM", "valid": True},
            {"time_seconds": 1.2, "center_xy": [735, 650], "depth_layer": "BEHIND_TRANSLUCENT_CURTAIN", "valid": "REQUIRES_CURTAIN_ALPHA_RECONSTRUCTION"},
            {"time_seconds": 1.8, "center_xy": [750, 930], "depth_layer": "BEHIND_TRANSLUCENT_CURTAIN", "valid": "REQUIRES_CURTAIN_ALPHA_RECONSTRUCTION"},
            {"time_seconds": 2.4, "center_xy": [760, 1160], "depth_layer": "EXPECTED_INTERIOR_DESK", "valid": False, "reason": "NO_INTERIOR_DESK_SURFACE_VISIBLE_IN_AUTHORITY_PLATE"},
        ],
        "terminal_geometry": {"paper_state": "HALF_UNFOLDED", "executable": False},
        "split_recommendation": {
            "v2a": "Authority-frame approach to the curtain top seam only; no crossing or landing.",
            "v2b": "Separately admitted interior-side plate with an actual visible desk surface, speaker mouth absent, and paper already entering the desk plane.",
        },
    }
    trajectory_path = asset_dir / "E40_U12_V2_DETERMINISTIC_TRAJECTORY_V1.json"
    write_json(trajectory_path, trajectory)

    files = {name: {"path": portable(asset_dir / name), "sha256": sha256(asset_dir / name)} for name in masks}
    files["depth_layers.png"] = {"path": portable(asset_dir / "depth_layers.png"), "sha256": sha256(asset_dir / "depth_layers.png")}
    files["geometry_overlay.png"] = {"path": portable(asset_dir / "geometry_overlay.png"), "sha256": sha256(asset_dir / "geometry_overlay.png")}
    files[trajectory_path.name] = {"path": portable(trajectory_path), "sha256": sha256(trajectory_path)}

    toolchain = {
        "schema": "qingshan.e40.u12.deterministic_compositor_manifest.v1",
        "status": "NO_SUBMIT_BLOCKED_BEFORE_LOCAL_VIDEO_RENDER",
        "authorization": False,
        "maximum_new_submissions": 0,
        "inputs": {
            "authority_frame": {"path": portable(FRAME), "sha256": EXPECTED[FRAME], "raw_pixel_role": "IMMUTABLE_FRAME0"},
            "failed_video_evidence": {"path": portable(FAILED_VIDEO), "sha256": EXPECTED[FAILED_VIDEO], "usage": "QA_EVIDENCE_ONLY_NOT_SOURCE_PIXELS"},
            "failure_qa": {"path": portable(FINAL_QA), "sha256": EXPECTED[FINAL_QA]},
            "failure_memory": {"path": portable(MEMORY), "sha256": EXPECTED[MEMORY]},
        },
        "generated_geometry_assets": files,
        "layer_order": ["BACKGROUND_PLATE", "INTERIOR_PAPER_IF_VALID", "CURTAIN_OCCLUDER", "FOREGROUND_DESK", "FOREGROUND_CHENJI"],
        "required_local_tools": [
            {"tool": "Python 3 + OpenCV", "role": "mask/depth/trajectory and deterministic alpha compositing"},
            {"tool": "FFmpeg FFV1 or PNG-sequence", "role": "lossless RGB frame0 preservation and zero-audio diagnostic container"},
            {"tool": "installed exact_first_frame_post_harvest_gate.py", "role": "decoded frame0 and true frame0-to-frame1 continuity"},
            {"tool": "installed frame_cadence_audit.py", "role": "cadence/freeze diagnostic"},
            {"tool": "installed final_video_ocr_audit.py", "role": "full-duration source OCR"},
        ],
        "render_contract": {
            "frame0_raw_rgb_sha256": "fa7827499f68545ac8a37d63e960340bba67fe1a9cb959e341a6632e2a285b1e",
            "audio_stream_count": 0,
            "mouth_nonvisible_full_duration": True,
            "paper_count": 1,
            "curtain_count": 1,
            "paper_terminal_state": "HALF_UNFOLDED",
            "test_asset_never_directly_assemblable": True,
        },
        "render_decision": "DO_NOT_RENDER_CURRENT_PLATE",
        "render_blockers": [
            "AUTHORITY_FRAME_CONTAINS_VISIBLE_CHENJI_PROFILE_MOUTH_PIXELS",
            "AUTHORITY_FRAME_HAS_NO_INTERIOR_DESK_RECEIVE_SURFACE_BEHIND_CURTAIN",
            "FRAME0_PIXEL_EXACT_AND_MOUTH_NONVISIBLE_FULL_DURATION_ARE_MUTUALLY_EXCLUSIVE",
        ],
        "provider_calls": 0,
        "tts_calls": 0,
        "transactions": 0,
        "credits": 0,
        "agentcut_actions": 0,
    }
    write_json(manifest_out, toolchain)

    failures = [
        {"code": "NO_INTERIOR_RECEIVE_PLANE", "evidence": "The only visible horizontal desk plane is in front of/overlapping the curtain occluder; the rear object is a narrow rail, not a desk surface."},
        {"code": "FRAME0_MOUTH_VISIBILITY_CONTRADICTION", "evidence": "The immutable authority frame includes non-uniform profile-mouth ROI pixels, so pixel-exact frame0 cannot also make the mouth absent."},
    ]
    qa = {
        "schema": "qingshan.e40.u12.deterministic_paper_transfer_machine_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "FAIL_CLOSED_NO_LOCAL_TEST_RENDER",
        "checks": {
            "installed_backlotos_v0_2_49": (Path("/Users/rogerwu/.local/share/backlotos/source/version").read_text(encoding="utf-8").strip() == "0.2.49"),
            "input_sha_bindings": True,
            "provider_tts_transaction_agentcut_zero": True,
            "paper_mask_nonempty": paper_pixels > 0,
            "depth_and_trajectory_emitted": True,
            "valid_interior_receive_plane": False,
            "frame0_pixel_exact_compatible_with_mouth_nonvisible": False,
            "local_test_render_allowed": False,
        },
        "measurements": {
            "authority_resolution": [width, height],
            "paper_mask_pixels": paper_pixels,
            "mouth_roi_luma_stddev": mouth_stddev,
            "foreground_desk_curtain_overlap_pixels": desk_curtain_overlap,
            "interior_receive_surface_count": 0,
        },
        "failures": failures,
        "toolchain_manifest": portable(manifest_out),
        "toolchain_manifest_sha256": sha256(manifest_out),
        "trajectory": portable(trajectory_path),
        "trajectory_sha256": sha256(trajectory_path),
        "policy": "Do not render a misleading test merely to produce media. Current authority cannot simultaneously preserve pixel-exact frame0, hide the mouth for the full duration, and land the paper on a physically present interior desk. Obtain a separately admitted interior-side plate or relax one hard contract under explicit authority.",
    }
    write_json(qa_out, qa)
    print(json.dumps({"status": qa["status"], "paper_mask_pixels": paper_pixels, "interior_receive_surface_count": 0, "mouth_roi_luma_stddev": mouth_stddev}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
