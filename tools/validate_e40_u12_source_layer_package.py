#!/usr/bin/env python3
"""Fail-closed local admission gate for the E40 U12 true-layer package.

This validator never creates media and never calls a provider.  It combines
direct file/container checks with exact-SHA evidence bindings.  Assertions that
cannot be established from the files themselves (camera parity, source
provenance, OCR and human QA) must be supplied by explicit receipts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PROVENANCE_TOKENS = (
    "INPAINT",
    "GENERATIVE_FILL",
    "SEGMENTED_FROM_FLATTENED",
    "SEGMENTATION_ONLY_FROM_FLATTENED",
    "WARP",
    "RESAMPLE",
    "CLONED_DESK",
    "MIRROR_PATCH",
    "QUARANTINED",
    "DIAGNOSTIC",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def decoded_rgb_sha(path: Path) -> str:
    with Image.open(path) as im:
        return hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_receipt_payload(receipt: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in receipt.items() if key != "signature_base64"}
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def resolve_repo_relative(raw: Any, failures: list[dict[str, Any]], code: str) -> Path | None:
    if not isinstance(raw, str) or not raw:
        failures.append({"code": code, "actual": raw, "expected": "non-empty repo-relative path"})
        return None
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        failures.append({"code": code, "actual": raw, "expected": "safe repo-relative path"})
        return None
    resolved = (ROOT / rel).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        failures.append({"code": code, "actual": raw, "expected": "path inside repository"})
        return None
    if not resolved.is_file():
        failures.append({"code": f"{code}_MISSING", "actual": raw, "expected": "existing regular file"})
        return None
    return resolved


def check_equal(failures: list[dict[str, Any]], code: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        failures.append({"code": code, "actual": actual, "expected": expected})


def check_sha(asset: dict[str, Any], label: str, failures: list[dict[str, Any]]) -> Path | None:
    path = resolve_repo_relative(asset.get("path"), failures, f"{label}_PATH")
    if path is None:
        return None
    actual = sha256_file(path)
    check_equal(failures, f"{label}_SHA256", asset.get("sha256"), actual)
    return path


def receipt_binds(
    receipt_ref: Any,
    expected_bindings: dict[str, str],
    label: str,
    expected_schema: str,
    expected_authority_purpose: str,
    trust_policy: dict[str, Any],
    contract_sha256: str,
    canonical_script_sha256: str,
    canonical_manifest_sha256: str,
    failures: list[dict[str, Any]],
) -> None:
    if not isinstance(receipt_ref, dict):
        failures.append({"code": f"{label}_REFERENCE", "actual": receipt_ref, "expected": "path+sha256 object"})
        return
    path = check_sha(receipt_ref, label, failures)
    if path is None:
        return
    try:
        receipt = load_json(path)
    except Exception as exc:  # fail closed on malformed evidence
        failures.append({"code": f"{label}_JSON", "actual": str(exc), "expected": "valid JSON object"})
        return
    check_equal(failures, f"{label}_SCHEMA", receipt.get("schema"), expected_schema)
    context = receipt.get("context") if isinstance(receipt.get("context"), dict) else {}
    check_equal(failures, f"{label}_CONTRACT_SHA256", context.get("contract_sha256"), contract_sha256)
    check_equal(failures, f"{label}_CANONICAL_SCRIPT_SHA256", context.get("canonical_script_sha256"), canonical_script_sha256)
    check_equal(failures, f"{label}_CANONICAL_MANIFEST_SHA256", context.get("canonical_manifest_sha256"), canonical_manifest_sha256)

    authority = receipt.get("authority") if isinstance(receipt.get("authority"), dict) else {}
    authority_id = authority.get("authority_id")
    algorithm = authority.get("algorithm")
    public_key_b64 = authority.get("public_key_raw_base64")
    declared_key_sha = authority.get("public_key_sha256")
    check_equal(failures, f"{label}_SIGNATURE_ALGORITHM", algorithm, "ED25519")
    key_bytes: bytes | None = None
    try:
        key_bytes = base64.b64decode(public_key_b64, validate=True)
        check_equal(failures, f"{label}_PUBLIC_KEY_LENGTH", len(key_bytes), 32)
        check_equal(failures, f"{label}_PUBLIC_KEY_SHA256", declared_key_sha, hashlib.sha256(key_bytes).hexdigest())
    except Exception as exc:
        failures.append({"code": f"{label}_PUBLIC_KEY_ENCODING", "actual": str(exc), "expected": "32-byte base64 Ed25519 public key"})

    trusted_authorities = trust_policy.get("trusted_authorities")
    trusted_authorities = trusted_authorities if isinstance(trusted_authorities, list) else []
    trusted = any(
        isinstance(row, dict)
        and row.get("authority_id") == authority_id
        and row.get("public_key_sha256") == declared_key_sha
        and row.get("purpose") == expected_authority_purpose
        and row.get("status") == "ADMITTED"
        for row in trusted_authorities
    )
    check_equal(failures, f"{label}_AUTHORITY_TRUSTED", trusted, True)

    signature_b64 = receipt.get("signature_base64")
    if key_bytes is not None and len(key_bytes) == 32:
        try:
            signature = base64.b64decode(signature_b64, validate=True)
            Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature, canonical_receipt_payload(receipt))
        except (ValueError, TypeError, InvalidSignature) as exc:
            failures.append({"code": f"{label}_SIGNATURE_INVALID", "actual": type(exc).__name__, "expected": "valid Ed25519 signature"})

    bindings = receipt.get("sha256_bindings")
    if not isinstance(bindings, dict):
        failures.append({"code": f"{label}_BINDINGS", "actual": bindings, "expected": expected_bindings})
        return
    for key, expected in expected_bindings.items():
        check_equal(failures, f"{label}_BINDING_{key.upper()}", bindings.get(key), expected)


def provenance_gate(package: dict[str, Any], failures: list[dict[str, Any]]) -> None:
    provenance = package.get("source_provenance")
    if not isinstance(provenance, dict):
        failures.append({"code": "SOURCE_PROVENANCE", "actual": provenance, "expected": "explicit provenance object"})
        return
    text = json.dumps(provenance, ensure_ascii=False).upper()
    hits = sorted(token for token in FORBIDDEN_PROVENANCE_TOKENS if token in text)
    if hits:
        failures.append({"code": "FORBIDDEN_SOURCE_PROVENANCE", "actual": hits, "expected": []})
    check_equal(failures, "CLEAN_PIXELS_SOURCE_OBSERVED", provenance.get("clean_hidden_pixels_source_observed"), True)
    check_equal(failures, "PAPER_LAYER_SOURCE_NATIVE", provenance.get("paper_layer_source_native_or_controlled_render"), True)
    check_equal(failures, "DEPTH_SOURCE_BOUND", provenance.get("depth_source_bound"), True)
    check_equal(failures, "SHADOW_SOURCE_OR_PARAMETER_BOUND", provenance.get("contact_shadow_source_or_parameter_bound"), True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--trust-policy", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-reject", action="store_true")
    args = parser.parse_args()

    contract_path = (ROOT / args.contract).resolve()
    package_path = (ROOT / args.package).resolve()
    trust_policy_path = (ROOT / args.trust_policy).resolve()
    out_path = (ROOT / args.out).resolve()
    failures: list[dict[str, Any]] = []

    contract = load_json(contract_path)
    package = load_json(package_path)
    trust_policy = load_json(trust_policy_path)
    check_equal(
        failures,
        "CONTRACT_SCHEMA",
        contract.get("schema"),
        "qingshan.e40.u12.v6.clean_desk_and_paper_layer_acquisition_contract.v1",
    )
    check_equal(failures, "PACKAGE_CONTRACT_SHA256", package.get("contract_sha256"), sha256_file(contract_path))
    check_equal(
        failures,
        "TRUST_POLICY_SCHEMA",
        trust_policy.get("schema"),
        "qingshan.e40.u12.v8.trusted_receipt_policy.v1",
    )
    check_equal(failures, "TRUST_POLICY_CONTRACT_SHA256", trust_policy.get("contract_sha256"), sha256_file(contract_path))
    check_equal(failures, "TRUST_POLICY_CANONICAL_SCRIPT_SHA256", trust_policy.get("canonical_script_sha256"), contract.get("canonical_script_sha256"))
    check_equal(failures, "TRUST_POLICY_CANONICAL_MANIFEST_SHA256", trust_policy.get("canonical_manifest_sha256"), contract.get("canonical_manifest_sha256"))
    check_equal(failures, "AUTHORIZATION_FALSE", package.get("authorization"), False)
    check_equal(failures, "MAXIMUM_NEW_SUBMISSIONS_ZERO", package.get("maximum_new_submissions"), 0)
    check_equal(failures, "PROVIDER_POST_FALSE", package.get("provider_post_allowed"), False)

    canonical = package.get("canonical") if isinstance(package.get("canonical"), dict) else {}
    check_equal(failures, "CANONICAL_SCRIPT_SHA256", canonical.get("script_sha256"), contract.get("canonical_script_sha256"))
    check_equal(failures, "CANONICAL_MANIFEST_SHA256", canonical.get("manifest_sha256"), contract.get("canonical_manifest_sha256"))

    assets = package.get("assets") if isinstance(package.get("assets"), dict) else {}
    clean = assets.get("clean_plate") if isinstance(assets.get("clean_plate"), dict) else {}
    rgba = assets.get("paper_rgba") if isinstance(assets.get("paper_rgba"), dict) else {}
    alpha = assets.get("paper_alpha") if isinstance(assets.get("paper_alpha"), dict) else {}
    depth = assets.get("paper_depth") if isinstance(assets.get("paper_depth"), dict) else {}
    shadow = assets.get("contact_shadow_alpha") if isinstance(assets.get("contact_shadow_alpha"), dict) else {}
    binding = assets.get("shadow_binding") if isinstance(assets.get("shadow_binding"), dict) else {}

    clean_path = check_sha(clean, "CLEAN_PLATE", failures)
    rgba_path = check_sha(rgba, "PAPER_RGBA", failures)
    alpha_path = check_sha(alpha, "PAPER_ALPHA", failures)
    depth_path = check_sha(depth, "PAPER_DEPTH", failures)
    shadow_path = check_sha(shadow, "CONTACT_SHADOW_ALPHA", failures)
    binding_path = check_sha(binding, "SHADOW_BINDING", failures)

    expected_size = tuple(contract["camera_and_clean_plate_hard_gates"]["dimensions_exact"])
    if clean_path:
        with Image.open(clean_path) as im:
            check_equal(failures, "CLEAN_PLATE_MODE", im.mode, "RGB")
            check_equal(failures, "CLEAN_PLATE_DIMENSIONS", im.size, expected_size)
        check_equal(failures, "CLEAN_DECODED_RGB_SHA256", clean.get("decoded_rgb_sha256"), decoded_rgb_sha(clean_path))

    rgba_alpha_bytes: bytes | None = None
    if rgba_path:
        with Image.open(rgba_path) as im:
            check_equal(failures, "PAPER_RGBA_MODE", im.mode, "RGBA")
            check_equal(failures, "PAPER_RGBA_DIMENSIONS", im.size, expected_size)
            rgba_image = im.convert("RGBA")
            alpha_channel = rgba_image.getchannel("A")
            rgba_alpha_bytes = alpha_channel.tobytes()
            extrema = alpha_channel.getextrema()
            has_nonbinary = extrema[0] < extrema[1] and any(v not in (0, 255) for v in alpha_channel.getdata())
            check_equal(failures, "PAPER_RGBA_NONBINARY_EDGE_ALPHA", has_nonbinary, True)
            transparent_rgb_zero = all(
                a != 0 or (r == 0 and g == 0 and b == 0)
                for r, g, b, a in rgba_image.getdata()
            )
            check_equal(failures, "PAPER_RGBA_RGB_ZERO_WHERE_ALPHA_ZERO", transparent_rgb_zero, True)

    if alpha_path:
        with Image.open(alpha_path) as im:
            check_equal(failures, "PAPER_ALPHA_DIMENSIONS", im.size, expected_size)
            check_equal(failures, "PAPER_ALPHA_MODE", im.mode in ("L", "I;16", "I;16B", "I;16L"), True)
            if rgba_alpha_bytes is not None:
                check_equal(
                    failures,
                    "PAPER_ALPHA_MATCHES_RGBA",
                    im.convert("L").tobytes() == rgba_alpha_bytes,
                    True,
                )

    if depth_path:
        with Image.open(depth_path) as im:
            check_equal(failures, "PAPER_DEPTH_DIMENSIONS", im.size, expected_size)
            check_equal(failures, "PAPER_DEPTH_16BIT", im.mode in ("I;16", "I;16B", "I;16L", "I"), True)

    if shadow_path:
        with Image.open(shadow_path) as im:
            check_equal(failures, "CONTACT_SHADOW_DIMENSIONS", im.size, expected_size)
            check_equal(failures, "CONTACT_SHADOW_ALPHA_MODE", im.mode in ("L", "I;16", "I;16B", "I;16L"), True)

    asset_shas = {
        "clean_plate": clean.get("sha256"),
        "paper_rgba": rgba.get("sha256"),
        "paper_alpha": alpha.get("sha256"),
        "paper_depth": depth.get("sha256"),
        "contact_shadow_alpha": shadow.get("sha256"),
        "shadow_binding": binding.get("sha256"),
    }
    exact_asset_shas = {k: v for k, v in asset_shas.items() if isinstance(v, str) and len(v) == 64}

    if binding_path:
        try:
            binding_doc = load_json(binding_path)
            for key in ("paper_rgba", "paper_alpha", "paper_depth", "contact_shadow_alpha"):
                check_equal(failures, f"SHADOW_BINDING_{key.upper()}", binding_doc.get("sha256_bindings", {}).get(key), asset_shas.get(key))
            check_equal(failures, "SHADOW_BINDING_RECEIVE_PLANE", isinstance(binding_doc.get("receive_plane"), dict), True)
            check_equal(failures, "SHADOW_BINDING_OFFSET", isinstance(binding_doc.get("offset"), dict), True)
            check_equal(failures, "SHADOW_BINDING_DEPTH_RELATION", isinstance(binding_doc.get("depth_relation"), dict), True)
        except Exception as exc:
            failures.append({"code": "SHADOW_BINDING_JSON", "actual": str(exc), "expected": "valid binding JSON"})

    provenance_gate(package, failures)
    receipt_binds(
        package.get("source_provenance_receipt"),
        exact_asset_shas,
        "SOURCE_PROVENANCE_RECEIPT",
        "qingshan.e40.u12.source_provenance_receipt.v1",
        "PRODUCTION_SOURCE_AUTHORITY",
        trust_policy,
        sha256_file(contract_path),
        contract.get("canonical_script_sha256"),
        contract.get("canonical_manifest_sha256"),
        failures,
    )

    gates = package.get("gates") if isinstance(package.get("gates"), dict) else {}
    clean_gates = gates.get("clean_plate") if isinstance(gates.get("clean_plate"), dict) else {}
    paper_gates = gates.get("paper_layer") if isinstance(gates.get("paper_layer"), dict) else {}
    check_equal(failures, "CLEAN_PEOPLE_FACES_HANDS_MOUTHS", clean_gates.get("people_faces_hands_mouths"), [0, 0, 0, 0])
    check_equal(failures, "CLEAN_PAPER_SEAL_COUNT", clean_gates.get("paper_and_seal_count"), [0, 0])
    check_equal(failures, "CLEAN_OCR0", clean_gates.get("ocr_visible_text_count"), 0)
    check_equal(failures, "CLEAN_SSIM", isinstance(clean_gates.get("immutable_background_region_ssim"), (int, float)) and clean_gates["immutable_background_region_ssim"] >= 0.995, True)
    check_equal(failures, "CLEAN_MAE", isinstance(clean_gates.get("immutable_background_region_mae"), (int, float)) and clean_gates["immutable_background_region_mae"] <= 1.0, True)
    check_equal(failures, "CLEAN_HOMOGRAPHY_ERROR", isinstance(clean_gates.get("homography_reprojection_error_px"), (int, float)) and clean_gates["homography_reprojection_error_px"] <= 0.5, True)
    check_equal(failures, "CLEAN_HUMAN_SCORE", isinstance(clean_gates.get("human_score"), (int, float)) and clean_gates["human_score"] >= 80, True)
    check_equal(failures, "PAPER_COMPONENT_COUNT", paper_gates.get("paper_connected_component_count"), 1)
    check_equal(failures, "PAPER_SEAL_COUNT", paper_gates.get("seal_count"), 1)
    check_equal(failures, "PAPER_OCR0", paper_gates.get("ocr_visible_text_count"), 0)
    check_equal(failures, "PAPER_DESK_CONTAMINATION_ZERO", paper_gates.get("desk_pixel_contamination"), "ZERO")
    check_equal(failures, "PAPER_CURTAIN_OCCLUSION", paper_gates.get("curtain_occlusion_relationship"), "PAPER_ENTIRELY_BEHIND_FOREGROUND_CURTAIN")
    check_equal(failures, "PAPER_HUMAN_SCORE", isinstance(paper_gates.get("human_score"), (int, float)) and paper_gates["human_score"] >= 80, True)

    evidence_receipt = package.get("qa_evidence_receipt")
    receipt_binds(
        evidence_receipt,
        exact_asset_shas,
        "QA_EVIDENCE_RECEIPT",
        "qingshan.e40.u12.qa_evidence_receipt.v1",
        "PRODUCTION_QA_AUTHORITY",
        trust_policy,
        sha256_file(contract_path),
        contract.get("canonical_script_sha256"),
        contract.get("canonical_manifest_sha256"),
        failures,
    )

    status = "PASS_FULL_SOURCE_LAYER_PACKAGE_ADMITTED_LOCAL_ONLY" if not failures else "FAIL_CLOSED_SOURCE_LAYER_PACKAGE_REJECTED"
    receipt = {
        "schema": "qingshan.e40.u12.v7.source_layer_admission_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "contract": args.contract,
        "contract_sha256": sha256_file(contract_path),
        "trust_policy": args.trust_policy,
        "trust_policy_sha256": sha256_file(trust_policy_path),
        "package": args.package,
        "package_sha256": sha256_file(package_path),
        "checks_run": 1,
        "failure_count": len(failures),
        "failures": failures,
        "failure_behavior": "NO_RENDER_NO_SUBMIT_NO_TRANSACTION_NO_CREDITS_NO_ASSEMBLY",
        "side_effects": {
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "agentcut_actions": 0,
            "assembly_actions": 0,
            "work_queue_changed": False,
            "e38_state_changed": False,
            "e39_state_changed": False,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "failure_count": len(failures), "out": args.out}, ensure_ascii=False))

    if args.expect_reject:
        return 0 if failures else 3
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
