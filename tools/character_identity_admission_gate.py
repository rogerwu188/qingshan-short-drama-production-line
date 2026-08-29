#!/usr/bin/env python3
"""Objective character-identity admission against canonical face anchors.

The gate keeps the registered ``CHARACTER-IDENTITY-ADMISSION`` gate_id. A
strong machine score may admit without a human reviewer; only the configured
boundary band requires human arbitration. InsightFace is loaded lazily so a
missing runtime fails loudly instead of silently falling back to a checklist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Protocol


GATE_ID = "CHARACTER-IDENTITY-ADMISSION"
METHOD = "INSIGHTFACE_COSINE_V1"
DEFAULT_GATE_REGISTRY = Path(__file__).resolve().parents[1] / "configs/GATE_REGISTRY_v3_20260716.json"


class EmbeddingBackend(Protocol):
    def embed(self, path: Path) -> list[float]: ...


class InsightFaceBackend:
    """Lazy InsightFace/ONNX backend used by the production CLI."""

    def __init__(self, model_name: str = "buffalo_l") -> None:
        try:
            import cv2  # type: ignore
            from insightface.app import FaceAnalysis  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("INSIGHTFACE_RUNTIME_UNAVAILABLE") from exc
        self._cv2 = cv2
        self._app = FaceAnalysis(name=model_name, providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=-1, det_size=(640, 640))

    def embed_all(self, path: Path) -> list[list[float]]:
        image = self._cv2.imread(str(path))
        if image is None:
            raise RuntimeError(f"IMAGE_DECODE_FAILED:{path}")
        faces = self._app.get(image)
        if not faces:
            raise RuntimeError(f"FACE_COUNT_ZERO:{path}")
        return [[float(value) for value in face.normed_embedding] for face in faces]

    def embed(self, path: Path) -> list[float]:
        embeddings = self.embed_all(path)
        if len(embeddings) != 1:
            raise RuntimeError(f"FACE_COUNT_NOT_ONE:{path}:{len(embeddings)}")
        return embeddings[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("EMBEDDING_DIMENSION_INVALID")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if not left_norm or not right_norm:
        raise ValueError("EMBEDDING_ZERO_NORM")
    return dot / (left_norm * right_norm)


def _paths(row: dict[str, Any], key: str) -> list[Path]:
    return [Path(str(value)) for value in row.get(key) or []]


def _verify_files(paths: list[Path], declared: dict[str, str], prefix: str) -> list[str]:
    failures: list[str] = []
    for path in paths:
        if not path.is_file():
            failures.append(f"{prefix}_missing:{path}")
            continue
        expected = str(declared.get(str(path)) or "")
        if not expected:
            failures.append(f"{prefix}_sha_missing:{path}")
        elif expected != _sha256(path):
            failures.append(f"{prefix}_sha_mismatch:{path}")
    return failures


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate(
    manifest: dict[str, Any],
    registry: dict[str, Any],
    backend: EmbeddingBackend | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    parameters = registry.get("parameters") or {}
    canonical_min = int(parameters.get("canonical_views_min", 3))
    samples_min = int(parameters.get("sample_frames_per_source_min", 3))
    pass_threshold = float(parameters.get("embedding_cosine_pass_threshold", 0.45))
    fail_threshold = float(parameters.get("embedding_cosine_fail_threshold", 0.30))
    boundary_midpoint = float(parameters.get("embedding_cosine_boundary_auto_decision_midpoint", 0.375))
    timeout_minutes = int(parameters.get("boundary_human_timeout_minutes", 15))
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    requested_value = str(manifest.get("boundary_human_review_requested_at") or "")
    requested_at = _utc(requested_value) if requested_value else None
    timeout_reached = bool(
        requested_at and (now_utc - requested_at).total_seconds() >= timeout_minutes * 60
    )
    failures: list[str] = []
    boundary: list[str] = []
    decisions: list[dict[str, Any]] = []
    sources = manifest.get("sources") or []
    if not sources:
        failures.append("identity_sources_missing")

    if backend is None:
        try:
            backend = InsightFaceBackend(str(parameters.get("embedding_model", "buffalo_l")))
        except RuntimeError as exc:
            failures.append(str(exc))

    for source in sources:
        source_id = str(source.get("source_id") or "UNKNOWN")
        rows = source.get("characters") or []
        if not rows:
            failures.append(f"source_character_evidence_missing:{source_id}")
        for row in rows:
            character_id = str(row.get("character_id") or "UNKNOWN")
            prefix = f"{source_id}:{character_id}"
            if character_id not in (registry.get("characters") or {}):
                failures.append(f"character_not_registered:{prefix}")
                continue
            references = _paths(row, "canonical_reference_paths")
            samples = _paths(row, "sample_frame_paths")
            local_failures: list[str] = []
            canonical_view_count = int(row.get("canonical_view_count") or len(references))
            if canonical_view_count < canonical_min:
                local_failures.append(f"canonical_views_below_min:{prefix}:{canonical_view_count}<{canonical_min}")
            if len(samples) < samples_min:
                local_failures.append(f"identity_sample_frames_below_min:{prefix}:{len(samples)}<{samples_min}")
            local_failures.extend(_verify_files(references, row.get("canonical_reference_sha256") or {}, "canonical_reference"))
            local_failures.extend(_verify_files(samples, row.get("sample_frame_sha256") or {}, "sample_frame"))
            failures.extend(local_failures)
            if backend is None or local_failures:
                continue
            try:
                reference_embeddings: list[list[float]] = []
                for path in references:
                    embed_all = getattr(backend, "embed_all", None)
                    if callable(embed_all):
                        reference_embeddings.extend(embed_all(path))
                    else:
                        reference_embeddings.append(backend.embed(path))
                sample_embeddings = [backend.embed(path) for path in samples]
                scores = [max(_cosine(sample, ref) for ref in reference_embeddings) for sample in sample_embeddings]
            except (RuntimeError, ValueError) as exc:
                failures.append(f"embedding_failed:{prefix}:{exc}")
                continue
            aggregate = float(median(scores))
            if aggregate >= pass_threshold:
                decision = "PASS"
            elif aggregate < fail_threshold:
                decision = "FAIL"
                failures.append(f"identity_embedding_below_fail_threshold:{prefix}:{aggregate:.6f}")
            else:
                if timeout_reached and aggregate >= boundary_midpoint:
                    decision = "ADMIT_BEST_EFFORT"
                elif timeout_reached:
                    decision = "SWITCH_COVERAGE"
                    failures.append(f"identity_boundary_auto_switch_coverage:{prefix}:{aggregate:.6f}")
                else:
                    decision = "BOUNDARY_REQUIRES_HUMAN"
                    boundary.append(prefix)
            decisions.append({
                "source_id": source_id,
                "character_id": character_id,
                "canonical_view_count": canonical_view_count,
                "canonical_face_embedding_count": len(reference_embeddings),
                "sample_scores": [round(value, 6) for value in scores],
                "aggregate_median": round(aggregate, 6),
                "decision": decision,
            })

    if boundary and requested_at is None:
        requested_at = now_utc
    auto_resolved = timeout_reached and any(
        row["decision"] in {"ADMIT_BEST_EFFORT", "SWITCH_COVERAGE"} for row in decisions
    )
    auto_directions = sorted({
        row["decision"] for row in decisions
        if row["decision"] in {"ADMIT_BEST_EFFORT", "SWITCH_COVERAGE"}
    })
    status = "FAIL" if failures else "BOUNDARY_REQUIRES_HUMAN" if boundary else "PASS"
    return {
        "schema": "qingshan.character_identity_admission_gate.v3",
        "gate_id": GATE_ID,
        "status": status,
        "source_count": len(sources),
        "reviewer_type": "AI_VISUAL",
        "objective_verification": {
            "method": METHOD,
            "decision": status,
            "pass_threshold": pass_threshold,
            "fail_threshold": fail_threshold,
            "boundary_auto_decision_midpoint": boundary_midpoint,
            "boundary_human_timeout_minutes": timeout_minutes,
            "canonical_views_min": canonical_min,
            "sample_frames_per_source_min": samples_min,
            "boundary_requires_human": True,
            "decisions": decisions,
        },
        "boundary_items": boundary,
        "boundary_human_review_requested_at": requested_at.isoformat().replace("+00:00", "Z") if requested_at else None,
        "boundary_auto_resolved_after_timeout": auto_resolved,
        "boundary_auto_resolution_directions": auto_directions,
        "admission_tier": (
            "FAIL" if status == "FAIL" else
            "ADMITTED_WITH_P2" if "ADMIT_BEST_EFFORT" in auto_directions else
            "ADMITTED" if status == "PASS" else "PENDING_HUMAN"
        ),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--gate-registry", default=str(DEFAULT_GATE_REGISTRY))
    parser.add_argument("--prior-report")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    character_registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    gate_registry = json.loads(Path(args.gate_registry).read_text(encoding="utf-8"))
    policy = next(
        (row.get("parameters") or {} for row in gate_registry.get("gates") or [] if row.get("gate_id") == GATE_ID),
        None,
    )
    if policy is None:
        raise SystemExit("CHARACTER_IDENTITY_GATE_POLICY_NOT_REGISTERED")
    character_registry = {**character_registry, "parameters": policy}
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.prior_report and not manifest.get("boundary_human_review_requested_at"):
        prior = json.loads(Path(args.prior_report).read_text(encoding="utf-8"))
        manifest["boundary_human_review_requested_at"] = prior.get("boundary_human_review_requested_at")
    report = evaluate(manifest, character_registry)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
