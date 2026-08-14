#!/usr/bin/env python3
"""Render a zero-cost deterministic U12 paper-settle diagnostic twice.

The immutable admitted V3 plate is frame 0. Later frames isolate its single
paper, reconstruct only the desk pixels hidden by that paper for diagnostic
purposes, and move every paper trajectory landmark monotonically downward.
The reconstructed underlay is explicitly non-authoritative and therefore this
tool proves compositor feasibility, not final source admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "working_assets/e40_production_20260809/u12_v3_interior_desk_mouth_absent_plate_v1/E40-U12-V3-INTERIOR-DESK-MOUTH-ABSENT-PLATE-V1_562bcf99-ee03-48fa-9a57-f774f75a52d2.png"
MEMORY = ROOT / "workflow/local_lora/seedance2_prompt_failure_training.jsonl"
EXPECTED_AUTHORITY_SHA = "6f99b0d16ec7c63ffa6314d8315b2aba45ac0645dac2f3c5bbe6438b3a2cbed8"
EXPECTED_MEMORY_SHA = "f0f5ce3a914306c51a6314204f9c980bd18e67c15b612a7948509e9b8697feb0"


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


def isolate_paper(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    # Original-resolution hand-audited visible silhouette. The left edge is
    # intentionally clipped at the curtain occluder because the paper is
    # already on the interior side in the admitted V3 plate.
    probable = polygon_mask(
        (height, width),
        [[304, 738], [596, 714], [625, 837], [879, 942], [808, 963],
         [526, 1009], [470, 991], [408, 921], [345, 839]],
    )
    sure = polygon_mask(
        (height, width),
        [[337, 754], [575, 733], [603, 835], [828, 936], [514, 984], [432, 914], [374, 841]],
    )
    grab = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
    grab[probable > 0] = cv2.GC_PR_FGD
    grab[sure > 0] = cv2.GC_FGD
    cv2.setRNGSeed(40)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    cv2.grabCut(image, grab, None, background, foreground, 6, cv2.GC_INIT_WITH_MASK)
    binary = np.where((grab == cv2.GC_FGD) | (grab == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    binary = cv2.bitwise_and(binary, probable)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((13, 13), np.uint8), iterations=2)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise RuntimeError("paper segmentation produced no component")
    contour = max(contours, key=cv2.contourArea)
    final = np.zeros_like(binary)
    cv2.drawContours(final, [contour], -1, 255, thickness=cv2.FILLED)
    return final


def encode_lossless(frame_dir: Path, output: Path, fps: int) -> None:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-fflags", "+bitexact", "-framerate", str(fps),
        "-i", str(frame_dir / "frame_%04d.png"),
        "-an", "-map_metadata", "-1", "-c:v", "ffv1", "-level", "3",
        "-g", "1", "-slicecrc", "1", "-pix_fmt", "bgr0", "-flags:v", "+bitexact",
        str(output),
    ]
    subprocess.run(command, check=True)


def render_frames(
    image: np.ndarray,
    clean: np.ndarray,
    paper_alpha: np.ndarray,
    curtain_mask: np.ndarray,
    frame_dir: Path,
    frame_count: int,
) -> list[dict]:
    height, width = image.shape[:2]
    source_quad = np.float32([[305, 739], [595, 716], [877, 943], [522, 1006]])
    # V2 cadence repair: a clearly visible 2-second downward settle. Every
    # landmark still moves only toward larger image Y, while the unequal
    # displacements compress the high arch without flattening the front curl.
    final_quad = np.float32([[319, 790], [608, 770], [875, 975], [530, 1025]])
    rgba = np.dstack([image, paper_alpha])
    trajectory = []
    for index in range(frame_count):
        if index == 0:
            frame = image.copy()
            progress = 0.0
            quad = source_quad.copy()
        else:
            progress = index / (frame_count - 1)
            # Smoothstep is monotonic and has no reverse/upward phase.
            eased = progress * progress * (3.0 - 2.0 * progress)
            quad = source_quad + (final_quad - source_quad) * eased
            matrix = cv2.getPerspectiveTransform(source_quad, quad)
            warped = cv2.warpPerspective(
                rgba, matrix, (width, height), flags=cv2.INTER_LANCZOS4,
                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0),
            )
            alpha = warped[..., 3].astype(np.float32) / 255.0
            # Deterministic contact shadow follows the paper downward.
            shadow = cv2.GaussianBlur(alpha, (0, 0), 8.0)
            shadow = cv2.warpAffine(shadow, np.float32([[1, 0, 2], [0, 1, 7]]), (width, height))
            base = clean.astype(np.float32)
            base *= (1.0 - 0.22 * shadow[..., None])
            frame = (warped[..., :3].astype(np.float32) * alpha[..., None] + base * (1.0 - alpha[..., None]))
            frame = np.clip(frame, 0, 255).astype(np.uint8)
            # Restore the admitted curtain as a foreground occluder.
            frame[curtain_mask > 0] = image[curtain_mask > 0]
        cv2.imwrite(str(frame_dir / f"frame_{index:04d}.png"), frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        trajectory.append({
            "frame": index,
            "time_seconds": round(index / 24.0, 6),
            "progress": round(progress, 8),
            "top_left_y": round(float(quad[0, 1]), 4),
            "top_right_y": round(float(quad[1, 1]), 4),
            "front_right_y": round(float(quad[2, 1]), 4),
            "front_left_y": round(float(quad[3, 1]), 4),
        })
    return trajectory


def contact_sheet(video: Path, output: Path) -> None:
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vf", "fps=4,scale=504:-1,tile=4x3:padding=8:margin=8:color=black",
        "-frames:v", "1", str(output),
    ], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--fps", type=int, default=24)
    args = parser.parse_args()
    out_dir = (ROOT / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if sha256(AUTHORITY) != EXPECTED_AUTHORITY_SHA:
        raise SystemExit("admitted V3 authority SHA mismatch")
    if sha256(MEMORY) != EXPECTED_MEMORY_SHA:
        raise SystemExit("V4 failure-memory SHA mismatch; rebind before rendering")
    image = cv2.imread(str(AUTHORITY), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (1792, 1008):
        raise SystemExit("authority image decode/dimensions failed")
    height, width = image.shape[:2]
    paper_mask = isolate_paper(image)
    if not 70000 <= int(np.count_nonzero(paper_mask)) <= 260000:
        raise SystemExit(f"paper mask area outside audited bounds: {np.count_nonzero(paper_mask)}")
    alpha = cv2.GaussianBlur(paper_mask, (0, 0), 1.2)
    inpaint_mask = cv2.dilate(paper_mask, np.ones((17, 17), np.uint8), iterations=1)
    clean = cv2.inpaint(image, inpaint_mask, 11, cv2.INPAINT_TELEA)
    curtain_mask = polygon_mask((height, width), [[0, 0], [307, 0], [307, 1110], [286, 1130], [0, 1120]])
    desk_mask = polygon_mask((height, width), [[306, 714], [1007, 700], [1007, 1360], [286, 1350]])
    mouth_mask = np.zeros((height, width), np.uint8)
    depth = np.zeros((height, width), np.uint8)
    depth[desk_mask > 0] = 96
    depth[paper_mask > 0] = 192
    depth[curtain_mask > 0] = 255
    cv2.imwrite(str(out_dir / "paper_mask.png"), paper_mask)
    cv2.imwrite(str(out_dir / "paper_alpha.png"), alpha)
    cv2.imwrite(str(out_dir / "curtain_occluder_mask.png"), curtain_mask)
    cv2.imwrite(str(out_dir / "desk_receive_plane_mask.png"), desk_mask)
    cv2.imwrite(str(out_dir / "mouth_visibility_roi_mask.png"), mouth_mask)
    cv2.imwrite(str(out_dir / "depth_layers.png"), depth)
    cv2.imwrite(str(out_dir / "diagnostic_clean_desk_non_authoritative.png"), clean)
    cv2.imwrite(str(out_dir / "paper_layer_rgba.png"), np.dstack([image, alpha]))

    frame_count = int(round(args.duration * args.fps))
    if frame_count < 48:
        raise SystemExit("diagnostic requires at least 48 frames")
    videos = []
    trajectories = []
    for label in ("a", "b"):
        with tempfile.TemporaryDirectory(prefix=f"e40_u12_v5_{label}_") as temporary:
            frame_dir = Path(temporary)
            trajectory = render_frames(image, clean, alpha, curtain_mask, frame_dir, frame_count)
            video = out_dir / f"E40_U12_V5_DETERMINISTIC_PAPER_SETTLE_RUN_{label.upper()}.mkv"
            encode_lossless(frame_dir, video, args.fps)
        videos.append(video)
        trajectories.append(trajectory)
    trajectory_path = out_dir / "E40_U12_V5_DETERMINISTIC_TRAJECTORY_V1.json"
    monotonic = all(
        all(current[key] >= previous[key] for key in ("top_left_y", "top_right_y", "front_right_y", "front_left_y"))
        for previous, current in zip(trajectories[0], trajectories[0][1:])
    )
    write_json(trajectory_path, {
        "schema": "qingshan.e40.u12.v5.deterministic_paper_trajectory.v1",
        "status": "PASS_MONOTONIC_DOWNWARD_DIAGNOSTIC",
        "authority_resolution": [width, height],
        "fps": args.fps,
        "frame_count": frame_count,
        "duration_seconds": args.duration,
        "monotonic_all_landmark_y": monotonic,
        "initial_geometry": "LOWER_EDGE_CONTACT_TOP_ARCH_RAISED",
        "terminal_geometry": "HALF_SPREAD_ARCH_RETAINED",
        "keyframes": [trajectories[0][0], trajectories[0][frame_count // 2], trajectories[0][-1]],
        "all_frames": trajectories[0],
        "source_authority_limitation": "Desk pixels hidden under the admitted paper are deterministically inpainted for feasibility only and are not admitted scene authority.",
    })
    sheet = out_dir / "E40_U12_V5_CONTACT_SHEET_4FPS_V1.jpg"
    contact_sheet(videos[0], sheet)
    assets = {}
    for path in sorted(out_dir.iterdir()):
        if path.is_file():
            assets[path.name] = {"path": portable(path), "sha256": sha256(path)}
    raw_frame0 = hashlib.sha256(image[:, :, ::-1].tobytes()).hexdigest()
    manifest = {
        "schema": "qingshan.e40.u12.v5.deterministic_compositor_no_submit_manifest.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_LOCAL_DIAGNOSTIC_RENDER_SOURCE_AUTHORITY_PENDING",
        "authorization": False,
        "maximum_new_submissions": 0,
        "provider_post_allowed": False,
        "inputs": {
            "admitted_v3_plate": {"path": portable(AUTHORITY), "sha256": EXPECTED_AUTHORITY_SHA, "role": "IMMUTABLE_FRAME0"},
            "v4_failure_memory": {"path": portable(MEMORY), "sha256": EXPECTED_MEMORY_SHA},
            "quarantined_v4_pixels_used": False,
        },
        "render_contract": {
            "frame0_decoded_rgb_sha256_expected": raw_frame0,
            "audio_stream_count": 0,
            "paper_count": 1,
            "visible_people_faces_mouths": [0, 0, 0],
            "paper_initial_reverse_upward_allowed": False,
            "paper_trajectory_landmark_y_monotonic": monotonic,
            "terminal_state": "HALF_SPREAD_NOT_FULLY_FLAT",
            "runs": 2,
            "bit_reproducible": sha256(videos[0]) == sha256(videos[1]),
        },
        "layer_order": ["DIAGNOSTIC_CLEAN_DESK_NON_AUTHORITY", "CONTACT_SHADOW", "EXTRACTED_PAPER", "ADMITTED_CURTAIN_OCCLUDER"],
        "generated_assets": assets,
        "source_authority_gate": {
            "status": "FAIL_PENDING_CLEAN_PREACTION_PLATE_OR_INDEPENDENT_TRANSPARENT_PAPER_AUTHORITY",
            "reason": "The admitted V3 frame contains the paper. Moving it exposes desk pixels that do not exist in the admitted source; deterministic inpainting proves renderer feasibility but cannot become production source authority.",
            "acceptable_unblockers": [
                "ADMITTED_CLEAN_INTERIOR_DESK_PREACTION_PLATE_WITH_IDENTICAL_CAMERA_LIGHTING",
                "INDEPENDENTLY_ADMITTED_TRANSPARENT_PAPER_LAYER_PLUS_ADMITTED_CLEAN_DESK_PLATE",
            ],
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "provider_calls": 0,
        "transactions": 0,
        "agentcut_actions": 0,
    }
    manifest_path = out_dir / "E40_U12_V5_DETERMINISTIC_COMPOSITOR_NO_SUBMIT_MANIFEST_V1.json"
    write_json(manifest_path, manifest)
    print(json.dumps({
        "status": manifest["status"],
        "paper_mask_pixels": int(np.count_nonzero(paper_mask)),
        "monotonic_downward": monotonic,
        "run_a_sha256": sha256(videos[0]),
        "run_b_sha256": sha256(videos[1]),
        "bit_reproducible": sha256(videos[0]) == sha256(videos[1]),
        "manifest": portable(manifest_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
