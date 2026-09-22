#!/usr/bin/env python3
"""Deterministically repair selected keyframe faces from locked identity plates.

This is a zero-provider-cost keyframe repair.  It uses InsightFace landmarks to
align a locked identity plate onto one detected output face and feather-blends
only the inner facial oval.  Scene, camera, blocking, wardrobe, hands, props and
all untargeted faces remain from the admitted composition.  The output is still
required to pass the normal exact-SHA Q1 gate; this tool never grants admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def face_app() -> FaceAnalysis:
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def sorted_faces(app: FaceAnalysis, image: np.ndarray):
    return sorted(app.get(image), key=lambda face: float((face.bbox[0] + face.bbox[2]) / 2.0))


def color_match(source: np.ndarray, target: np.ndarray, mask: np.ndarray) -> np.ndarray:
    out = source.astype(np.float32)
    chosen = mask > 0.25
    if not np.any(chosen):
        return source
    for channel in range(3):
        src = out[:, :, channel][chosen]
        dst = target[:, :, channel].astype(np.float32)[chosen]
        src_std = max(float(src.std()), 1.0)
        dst_std = max(float(dst.std()), 1.0)
        out[:, :, channel] = (out[:, :, channel] - float(src.mean())) * min(dst_std / src_std, 1.35) + float(dst.mean())
    return np.clip(out, 0, 255).astype(np.uint8)


def replace_face(canvas: np.ndarray, target_face, plate: np.ndarray, source_face, scale: float, blend: str) -> np.ndarray:
    matrix, _ = cv2.estimateAffinePartial2D(
        np.asarray(source_face.kps, dtype=np.float32),
        np.asarray(target_face.kps, dtype=np.float32),
        method=cv2.LMEDS,
    )
    if matrix is None:
        raise RuntimeError("LANDMARK_AFFINE_FAILED")
    height, width = canvas.shape[:2]
    warped = cv2.warpAffine(plate, matrix, (width, height), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101)
    x1, y1, x2, y2 = [float(value) for value in target_face.bbox]
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    if blend == "feature":
        # Restrict the transplant to the brows/eyes/nose/mouth core.  This keeps
        # the target hairline, temples, ears, cheeks and jaw, avoiding the visible
        # oval boundary that a large alpha/seamless mask can create on lit faces.
        keypoints = np.asarray(target_face.kps, dtype=np.float32)
        cx = float(keypoints[:, 0].mean())
        cy = float(keypoints[:, 1].mean() - (y2 - y1) * 0.01)
        axes = (max(4, int((x2 - x1) * 0.31 * scale)), max(4, int((y2 - y1) * 0.31 * scale)))
    else:
        axes = (max(4, int((x2 - x1) * 0.43 * scale)), max(4, int((y2 - y1) * 0.50 * scale)))
    hard = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(hard, (int(cx), int(cy + (y2 - y1) * 0.025)), axes, 0, 0, 360, 255, -1)
    # Keep the hairline and ears from the target frame; identity comes from the
    # brows/eyes/nose/mouth/cheeks/jaw inside this feathered oval.
    blur = max(9, int(min(axes) * (0.48 if blend == "feature" else 0.34)) | 1)
    alpha = cv2.GaussianBlur(hard, (blur, blur), 0).astype(np.float32) / 255.0
    alpha = np.clip(alpha * 1.08, 0.0, 1.0)
    matched = color_match(warped, canvas, alpha)
    if blend == "seamless":
        center = (int(cx), int(cy))
        return cv2.seamlessClone(matched, canvas, hard, center, cv2.NORMAL_CLONE)
    return np.clip(matched.astype(np.float32) * alpha[:, :, None] + canvas.astype(np.float32) * (1.0 - alpha[:, :, None]), 0, 255).astype(np.uint8)


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mapping", action="append", required=True,
                        help="JSON object with character_id, face_index and plate")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--blend", choices=("alpha", "seamless", "feature"), default="alpha")
    args = parser.parse_args()

    app = face_app()
    canvas = cv2.imread(str(args.input))
    if canvas is None:
        raise SystemExit(f"cannot decode {args.input}")
    targets = sorted_faces(app, canvas)
    mappings = [json.loads(value) for value in args.mapping]
    rows = []
    for mapping in mappings:
        index = int(mapping["face_index"])
        if index < 0 or index >= len(targets):
            raise SystemExit(f"face index {index} outside detected count {len(targets)}")
        plate_path = Path(mapping["plate"])
        plate = cv2.imread(str(plate_path))
        plate_faces = sorted_faces(app, plate) if plate is not None else []
        if len(plate_faces) != 1:
            raise SystemExit(f"identity plate must contain exactly one face: {plate_path}: {len(plate_faces)}")
        canvas = replace_face(canvas, targets[index], plate, plate_faces[0], args.scale, args.blend)
        rows.append({
            "character_id": mapping["character_id"],
            "target_face_index_left_to_right": index,
            "identity_plate": str(plate_path.resolve()),
            "identity_plate_sha256": digest(plate_path),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), canvas, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
        raise SystemExit(f"cannot write {args.output}")

    # Diagnostic only: maximum cosine per locked plate.  The normal Q1 builder
    # still performs the authoritative assignment and decision.
    final_faces = sorted_faces(app, canvas)
    for row in rows:
        plate = cv2.imread(row["identity_plate"])
        reference = sorted_faces(app, plate)[0].normed_embedding
        row["diagnostic_max_cosine"] = round(max(cosine(face.normed_embedding, reference) for face in final_faces), 6)
    report = {
        "schema": "nalu.keyframe_targeted_identity_plate_repair.v1",
        "status": "CANDIDATE_REQUIRES_NORMAL_Q1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input.resolve()),
        "input_sha256": digest(args.input),
        "output": str(args.output.resolve()),
        "output_sha256": digest(args.output),
        "detected_face_count": len(final_faces),
        "repair_scope": "INNER_FACE_OVAL_ONLY",
        "blend_mode": args.blend,
        "untargeted_pixels_policy": "PRESERVE_COMPOSITION_AND_ALL_NON_FACE_AUTHORITIES",
        "rows": rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
