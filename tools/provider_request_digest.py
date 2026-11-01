#!/usr/bin/env python3
"""Bind a review to the provider request that is actually sent.

Plan §7.  Every earlier receipt binds a FILE — the prompt file, the reference
files — and later steps (H3 re-render, reference reordering, voice attachment,
send-time image compression) can change what the provider receives without
touching any bound sha.  This module defines one digest over the request as
the submitter is about to POST it, so a reviewer can bind to that, and the
submitter can refuse — before any intent record, with zero POSTs — when the two
no longer match.

What the digest covers (the semantic request):
  prompt text, model, duration, aspect ratio, resolution, the ORDERED list of
  reference images by on-disk sha256 (with their declared roles), and the
  ordered audio references.
What it deliberately does not cover: the base64 bytes of each image.  Oversized
references are re-encoded at send time on a temp copy (giggle_api_client); that
is transport, recorded separately as sent_reference_sha256, and reviewing it
would make every review depend on a JPEG encoder.

Off for every episode by default (configs/PROVIDER_REQUEST_REVIEW_BINDING_V1.json).
A task that carries reviewed_request_sha256 is always checked, policy or not.

Three things a reader must never have to guess (line owner 2026-11-01, item 3)
-----------------------------------------------------------------------------
1. WHICH stage a record is at.  ``binding_block`` stamps every record with
   ``stage``, and every field that cannot exist yet is present with value
   ``null`` plus its reason in ``nulls``.  A task id is never invented and never
   back-filled from another task; a payload sha is never guessed.
2. WHETHER the check ran.  A record whose episode is outside the policy says
   ``UNENFORCED`` — never ``PASS``, never ``NOT_REQUIRED``.  Silence is not a
   pass.
3. WHAT the provider actually received.  ``bind_receipt`` takes the existing
   transaction file (workflow/tasks/giggle_submit_transactions/<EP>/*.json) and
   attaches its task id and provider echo to the SAME record, keyed by the
   request sha, refusing outright when the review request on disk no longer
   hashes to what the record says was reviewed.

Everything here is per task and cheap: no global lock, no batch barrier, no
extra provider call.  Every blocking switch ships off (see the policy config).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "qingshan.provider_request_digest.v1"
BINDING_SCHEMA = "qingshan.provider_request_binding.v1"
POLICY = Path(__file__).resolve().parents[1] / "configs" / "PROVIDER_REQUEST_REVIEW_BINDING_V1.json"

#: The four reference roles the line owner named (2026-11-01, item 1).  Every
#: authoring role — ``character``, ``character_wardrobe``, ``subspace_layout``,
#: ``prop``, ``ADMITTED_NEW_EVENT_ENTRY_STATE`` … — folds onto one of these, so a
#: reviewer reading two different manifests still sees one vocabulary.
REFERENCE_ROLES = ("IDENTITY", "WARDROBE", "SPACE", "PROP")
#: Anything that is the OUTPUT of the request, not a reference handed to it.
GENERATED_TARGET = "GENERATED_TARGET"
OTHER_ROLE = "OTHER"

#: Stages of one record.  A record is written at review time and is bound to a
#: provider task later; nothing moves it backwards.
STAGE_REVIEWED = "REVIEWED_BEFORE_SUBMISSION"
STAGE_BOUND = "SENT_TASK_ID_BOUND"
STAGE_UNBOUND = "SENT_WITHOUT_TASK_ID"
#: No authoring-manifest row describes this task, so there is no provider request
#: to bind to and no send to describe.  Distinct from the other three on purpose:
#: "nothing declares this" must not read as "it was sent and lost its id".
STAGE_NO_PROVIDER_ROW = "NO_PROVIDER_REQUEST_DECLARED"

#: Every value of ``status`` a binding block can report.  Only MATCH is a pass.
STATUS_MATCH = "MATCH"
STATUS_MISMATCH = "MISMATCH"
STATUS_MISSING = "MISSING"
STATUS_UNENFORCED = "UNENFORCED"
STATUS_INVALID = "INVALID"
STATUS_VALID = "VALID"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def payload_sha256(payload: Any) -> str:
    """sha256 of the request body exactly as serialised for the provider.

    Transport evidence, like ``sent_reference_sha256``: it proves that the body
    that left this machine is the body this record describes.
    """
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha_bytes(body.encode("utf-8"))


# --------------------------------------------------------------------------- #
# roles
# --------------------------------------------------------------------------- #
_ROLE_EXACT = {
    "character": "IDENTITY",
    "character_reference": "IDENTITY",
    "character_identity_reference": "IDENTITY",
    "identity": "IDENTITY",
    "identity_plate": "IDENTITY",
    "identity_reference": "IDENTITY",
    "face_reference": "IDENTITY",
    "operator_source_reference": "IDENTITY",
    "own_base_plate_same_identity": "IDENTITY",
    "own_locked_plates_same_identity": "IDENTITY",
    "h3_face_and_body_reference_not_identity_authority": "IDENTITY",
    "character_wardrobe": "WARDROBE",
    "wardrobe": "WARDROBE",
    "wardrobe_plate": "WARDROBE",
    "wardrobe_state": "WARDROBE",
    "wardrobe_state_on_identity_plate": "WARDROBE",
    "episode_global_space_map": "SPACE",
    "global_space_map": "SPACE",
    "subspace_layout": "SPACE",
    "space": "SPACE",
    "space_map": "SPACE",
    "scene": "SPACE",
    "place": "SPACE",
    "environment": "SPACE",
    "prop": "PROP",
    "prop_reference": "PROP",
    "prop_identity": "PROP",
    "object_reference": "PROP",
    "keyframe": GENERATED_TARGET,
    "start_frame_keyframe": GENERATED_TARGET,
    "unit_video": GENERATED_TARGET,
    "original_resolution_frame": GENERATED_TARGET,
    "contact_sheet_2fps": GENERATED_TARGET,
    "admitted_new_event_entry_state": GENERATED_TARGET,
    "previous_tail_frame": GENERATED_TARGET,
    "derived_start_frame": GENERATED_TARGET,
    "anonymised_synopsis": OTHER_ROLE,
}


def canonical_role(raw: Any) -> str:
    """Fold any authored role string onto IDENTITY / WARDROBE / SPACE / PROP."""
    token = re.sub(r"[^a-z0-9]+", "_", str(raw or "").strip().lower()).strip("_")
    if not token:
        return OTHER_ROLE
    if token in _ROLE_EXACT:
        return _ROLE_EXACT[token]
    # ``CHARACTER_PROP_...`` style labels: the first needle wins, so a combined
    # label never silently becomes "a prop reference".
    for needle, role in (("wardrobe", "WARDROBE"), ("identity", "IDENTITY"),
                         ("character", "IDENTITY"), ("space", "SPACE"),
                         ("prop", "PROP"), ("scene", "SPACE")):
        if needle in token:
            return role
    return OTHER_ROLE


def reference_evidence(rows: Iterable[Any], *, roles: Iterable[str] = REFERENCE_ROLES) -> list[dict[str, Any]]:
    """One row per reference image the request will actually carry.

    ``source_sha256`` is the file on disk (what the review could have been shown);
    ``transport_sha256`` is what was encoded for the wire (only known after the
    submitter encodes, so it is ``None`` with its reason at review time).  A
    reference whose file is gone is reported MISSING — never dropped, because a
    missing reference is exactly what a reviewer must be told about.
    """
    wanted = {str(role).upper() for role in roles}
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows or [], 1):
        if not isinstance(row, dict):
            continue
        role = canonical_role(row.get("role"))
        if wanted and role not in wanted:
            continue
        path = row.get("path")
        source = str(row.get("sha256") or "").strip().lower() or None
        transport = str(row.get("transport_sha256") or "").strip().lower() or None
        exists = bool(path) and Path(str(path)).is_file()
        if exists:
            on_disk = sha256_file(Path(str(path)))
            if source and on_disk and on_disk != source:
                # The manifest's sha is the reviewed one; say the file moved.
                state, reason = "CHANGED_SINCE_AUTHORED", "ON_DISK_SHA_DIFFERS_FROM_MANIFEST"
            else:
                state, reason = "PRESENT", None
                source = source or on_disk
        elif path:
            state, reason = "MISSING", "REFERENCE_FILE_NOT_ON_DISK"
        else:
            state, reason = "MISSING", "NO_REFERENCE_PATH_DECLARED"
        out.append({
            "index": index,
            "role": role,
            "declared_role": row.get("role"),
            "entity_id": row.get("entity_id") or row.get("character_id") or row.get("prop_id"),
            "path": str(path) if path else None,
            "version": str(row.get("version") or row.get("view") or row.get("kind")
                           or (f"sha256:{(source or '')[:12]}" if source else "") or "") or None,
            "source_sha256": source,
            "transport_sha256": transport,
            "status": state,
            "missing_reason": reason,
        })
    return out


# --------------------------------------------------------------------------- #
# the semantic digest (unchanged): what the submitter will POST
# --------------------------------------------------------------------------- #
def request_digest(
    *,
    prompt_text: str,
    model: Any,
    duration: Any = None,
    aspect_ratio: Any = None,
    resolution: Any = None,
    reference_sha256: Iterable[str] = (),
    reference_roles: Iterable[Any] | None = None,
    audio: Iterable[Any] = (),
) -> str:
    refs = list(reference_sha256)
    roles = list(reference_roles or [None] * len(refs))
    if len(roles) != len(refs):
        roles = (roles + [None] * len(refs))[: len(refs)]
    canonical = {
        "schema": SCHEMA,
        "prompt_sha256": _sha_bytes(str(prompt_text).encode("utf-8")),
        "model": str(model or ""),
        "duration": duration if duration is None else float(duration),
        "aspect_ratio": str(aspect_ratio or ""),
        "resolution": str(resolution or ""),
        # Order is part of the request: the provider reads @Image1..N by position.
        "references": [{"index": i, "sha256": sha, "role": (str(role) if role else None)}
                       for i, (sha, role) in enumerate(zip(refs, roles), 1)],
        "audio": [str(value) for value in audio],
    }
    return _sha_bytes(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def reference_roles_of(task: dict[str, Any]) -> list[Any]:
    """Roles in transmission order, when the task records them; None otherwise."""
    sequence = task.get("reference_image_sequence") or []
    if sequence and len(sequence) == len(task.get("reference_images") or []):
        return [row.get("role") if isinstance(row, dict) else None for row in sequence]
    return [None] * len(task.get("reference_images") or [])


def task_request_digest(task: dict[str, Any], *, prompt_text: str, reference_paths: list[Path],
                        duration: Any = None, audio: Iterable[Any] = ()) -> dict[str, Any]:
    """Digest of the request built from the very values the submitter will send."""
    shas = [_sha_bytes(Path(p).read_bytes()) for p in reference_paths]
    digest = request_digest(
        prompt_text=prompt_text, model=task.get("model"), duration=duration,
        aspect_ratio=task.get("aspect_ratio", "9:16"), resolution=task.get("resolution"),
        reference_sha256=shas, reference_roles=reference_roles_of(task), audio=audio,
    )
    return {"request_sha256": digest, "reference_sha256_in_send_order": shas}


def sent_audio_references(task: dict[str, Any]) -> list[str]:
    """The audio list exactly as the video submitter sends it: asset ids win, else URLs."""
    asset_ids = [*(task.get("exact_dialogue_audio_asset_ids") or []), *(task.get("reference_audio_asset_ids") or [])]
    if asset_ids:
        return [f"asset_id:{v}" for v in asset_ids]
    urls = [*(task.get("exact_dialogue_audio_urls") or []), *(task.get("reference_audio_urls") or [])]
    return [f"url:{v}" for v in urls]


def sent_image_sha256(images: Iterable[Any]) -> list[str]:
    """sha256 of each image exactly as transmitted (after any send-time re-encode).

    Transport evidence, not part of the reviewed digest: it shows whether the
    bytes the provider received are the bytes on disk.
    """
    import base64
    out = []
    for row in images or []:
        if isinstance(row, dict) and row.get("base64"):
            out.append(_sha_bytes(base64.b64decode(row["base64"])))
        elif isinstance(row, dict) and (row.get("asset_id") or row.get("url")):
            out.append("ref:" + str(row.get("asset_id") or row.get("url")))
        else:
            out.append("unknown")
    return out


# --------------------------------------------------------------------------- #
# policy
# --------------------------------------------------------------------------- #
def policy() -> dict[str, Any]:
    try:
        payload = json.loads(POLICY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def binding_required(task: dict[str, Any]) -> bool:
    config = policy()
    episode = str(task.get("episode") or "").upper()
    match = re.match(r"E(\d+)", episode)
    if not match:
        return False
    if episode[: match.end()] in {str(v).upper() for v in config.get("enabled_episodes") or []}:
        return True
    start = config.get("enabled_from_episode")
    return bool(isinstance(start, str) and re.fullmatch(r"E\d+", start.upper())
                and int(match.group(1)) >= int(start[1:]))


def enforcement_status(task: dict[str, Any]) -> str:
    """ENFORCED or UNENFORCED — never "PASS", never "NOT_REQUIRED"."""
    return "ENFORCED" if binding_required(task) else STATUS_UNENFORCED


def review_media_policy() -> dict[str, Any]:
    """The review-side rules (item 4), with the strict default when unconfigured.

    One switch, and it is honoured: ``identity_claim_requires_reference`` gates
    ``vlm_review_protocol.reference_claim_failures``.  Declaring a MISSING
    reference is deliberately NOT switchable — omitting one silently is the exact
    failure this rule exists to stop, so no config value may turn it back on.
    """
    section = policy().get("review_media") or {}
    if not isinstance(section, dict):
        section = {}
    return {"identity_claim_requires_reference":
            bool(section.get("identity_claim_requires_reference", True))}


def require_reviewed_request(task: dict[str, Any], computed: str) -> dict[str, Any]:
    """Raise before any intent record when the sent request is not the reviewed one."""
    reviewed = str(task.get("reviewed_request_sha256") or "").strip()
    required = binding_required(task)
    if reviewed and reviewed != computed:
        raise ValueError(
            f"{task.get('task_key')} REVIEWED_REQUEST_MISMATCH: the request about to be sent "
            f"({computed[:16]}) is not the reviewed request ({reviewed[:16]}); something changed "
            "prompt text, model parameters, reference order or audio after review"
        )
    if required and not reviewed:
        raise ValueError(f"{task.get('task_key')} REVIEWED_REQUEST_NOT_BOUND: no review is bound to this request")
    status = STATUS_MATCH if reviewed else STATUS_UNENFORCED
    return {"request_sha256": computed, "reviewed_request_sha256": reviewed or None,
            "binding_required": required, "enforcement": enforcement_status(task),
            "status": status,
            # A record that says only "NOT_REQUIRED" reads as a pass.  This note
            # is what makes an unenforced record legible in a receipt.
            "note": None if reviewed else
                    "no review is bound to this request and the policy does not require one;"
                    " the send is UNENFORCED, not verified"}


def bound_under_other_fingerprint(transaction_dir: Path, task_key: str, fingerprint: str) -> list[str]:
    """Transactions already bound to a provider task under a DIFFERENT fingerprint.

    The transaction store is keyed by task_key + fingerprint, so a recompile
    that changes any fingerprint input cannot see the earlier bound record and
    would POST again.  This finds those records.
    """
    hits = []
    for path in sorted(Path(transaction_dir).glob(f"{task_key}__*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(row.get("submission_fingerprint") or "") == fingerprint:
            continue
        if row.get("state") == "SUBMITTED_TASK_ID_BOUND" or row.get("task_id"):
            hits.append(str(row.get("submission_fingerprint") or path.name))
    return hits


def require_no_silent_resubmission(task: dict[str, Any], transaction_dir: Path, fingerprint: str) -> None:
    """Under the binding policy, a task_key already bound elsewhere needs an explicit supersede."""
    if not binding_required(task):
        return
    others = bound_under_other_fingerprint(transaction_dir, str(task.get("task_key")), fingerprint)
    declared = {str(v) for v in (task.get("supersedes_submission_fingerprints") or [])}
    undeclared = [fp for fp in others if fp not in declared]
    if undeclared:
        raise ValueError(
            f"{task.get('task_key')} BOUND_UNDER_OTHER_FINGERPRINT: already submitted as "
            f"{','.join(fp[:16] for fp in undeclared)}; a re-POST must declare "
            "supersedes_submission_fingerprints"
        )


# --------------------------------------------------------------------------- #
# the staged evidence record (items 1 and 2)
# --------------------------------------------------------------------------- #
def binding_block(provider_request: dict[str, Any] | None, *, episode: str, task_key: str,
                  kind: str, review_request_path: Any = None, review_request_sha256: Any = None,
                  task_id: Any = None, task_id_source: str | None = None,
                  payload_sha: Any = None, bound_at: Any = None) -> dict[str, Any]:
    """The block a Q1 / SFE evidence record carries beside its verdict.

    Built from what the authoring manifest declares plus what the review file
    hashes to.  Nothing here is derived from the asset under review, and nothing
    that does not exist yet is invented: it is ``null`` with a reason in
    ``nulls``, so an auditor can tell "not applicable yet" from "lost".
    """
    request = provider_request if isinstance(provider_request, dict) else {}
    references = reference_evidence(request.get("references") or [])
    identity_rows = [row for row in references if row["role"] == "IDENTITY"]
    reviewed_digest = str(request.get("reviewed_request_sha256") or "").strip() or None
    task = {"episode": episode}
    required = binding_required(task)

    nulls: dict[str, str] = {}
    if task_id is None:
        nulls["task_id"] = "NOT_YET_ASSIGNED_BY_PROVIDER"
    if payload_sha is None:
        nulls["payload_sha256"] = "NOT_YET_SERIALISED_AT_REVIEW_TIME"
    if reviewed_digest is None:
        nulls["request_sha256"] = "NO_REVIEWED_REQUEST_DIGEST_STAMPED_FOR_THIS_TASK"
    missing = [row for row in references if row["status"] != "PRESENT"]
    for row in missing:
        nulls[f"references[{row['index']}].source_sha256"] = row["missing_reason"] or "REFERENCE_MISSING"
    for row in references:
        if row["transport_sha256"] is None:
            nulls[f"references[{row['index']}].transport_sha256"] = "TRANSPORT_SHA_NOT_RECORDED_YET"
    if not request:
        nulls["provider_request"] = "NO_AUTHORING_MANIFEST_ROW_FOR_THIS_TASK"

    if task_id is not None:
        stage = STAGE_BOUND
    elif request:
        stage = STAGE_REVIEWED
    else:
        stage = STAGE_NO_PROVIDER_ROW

    return {
        "schema": BINDING_SCHEMA,
        "episode": episode,
        "task_key": task_key,
        "kind": kind,
        "stage": stage,
        "recorded_at": now(),
        "policy": {"policy_id": "PROVIDER_REQUEST_REVIEW_BINDING_V1",
                   "binding_required": required,
                   "status": enforcement_status(task)},
        "review": {
            "request_path": str(review_request_path) if review_request_path else None,
            "request_sha256": str(review_request_sha256) if review_request_sha256 else None,
        },
        "provider_request": {
            "manifest_task_key": request.get("manifest_task_key"),
            "model": request.get("model"),
            "prompt_file": request.get("prompt_file"),
            "prompt_sha256": request.get("prompt_sha256"),
            # The semantic digest the submitter re-checks at the paid boundary.
            "request_sha256": reviewed_digest,
        },
        "task_id": str(task_id) if task_id is not None else None,
        "task_id_source": task_id_source if task_id is not None else None,
        "payload_sha256": str(payload_sha) if payload_sha else None,
        "bound_at": bound_at if task_id is not None else None,
        "references": references,
        "identity_reference_status": (
            "PRESENT" if any(row["status"] == "PRESENT" for row in identity_rows)
            else "MISSING" if identity_rows else "NOT_DECLARED"),
        "nulls": nulls,
    }


def binding_still_valid(binding: dict[str, Any], *, prompt_text: Any = None,
                        reference_paths: Iterable[Any] | None = None, model: Any = None,
                        duration: Any = None, aspect_ratio: Any = None, resolution: Any = None,
                        audio: Iterable[Any] = (), payload_sha: Any = None,
                        computed_request_sha256: Any = None) -> dict[str, Any]:
    """Re-derive the review from the values in hand; any drift invalidates it.

    This is the item-3 test in function form: change the prompt text, a reference
    file, the model or the serialised payload and the answer is INVALID with
    ``re_review_required`` — there is no path where a changed request keeps a
    previously earned PASS.

    ``computed_request_sha256`` is the digest the submitter computed from the
    request it is about to send (``task_request_digest``).  It is the authority
    on the whole request, including the references this record does not list;
    the per-field arguments are what tell the reader WHICH input moved.
    """
    request = (binding or {}).get("provider_request") or {}
    reasons: list[str] = []
    required = bool(((binding or {}).get("policy") or {}).get("binding_required"))
    reviewed = str(request.get("request_sha256") or "").strip()
    if not reviewed:
        status = STATUS_UNENFORCED
        if required:
            status, reasons = STATUS_INVALID, ["NO_REVIEWED_REQUEST_DIGEST_BOUND"]
        return {"status": status, "reasons": reasons, "re_review_required": bool(reasons),
                "request_sha256": None,
                "identity_reference_status": (binding or {}).get("identity_reference_status")}

    bound_prompt = str(request.get("prompt_sha256") or "").strip()
    if prompt_text is not None and bound_prompt:
        if _sha_bytes(str(prompt_text).encode("utf-8")) != bound_prompt:
            reasons.append("PROMPT_TEXT_CHANGED")
    if model is not None and bound_prompt:
        if str(model) != str(request.get("model") or ""):
            reasons.append("MODEL_CHANGED")

    bound_refs = {i: row for i, row in enumerate((binding or {}).get("references") or [], 1)}
    # Only the references that were actually on disk are in the request; one
    # already recorded MISSING is a coverage gap (reported separately), not a
    # change to the request.
    present_refs = [(index, row) for index, row in sorted(bound_refs.items())
                    if row.get("status") == "PRESENT"]
    paths = [Path(str(p)) for p in (reference_paths if reference_paths is not None else ())]
    if reference_paths is not None:
        if len(paths) != len(present_refs):
            reasons.append(f"REFERENCE_COUNT_CHANGED:{len(paths)}!={len(present_refs)}")
        for position, path in enumerate(paths):
            if position >= len(present_refs):
                reasons.append(f"REFERENCE_ADDED:{path.name}")
                continue
            index, row = present_refs[position]
            on_disk = sha256_file(path)
            if on_disk is None or (row.get("source_sha256") and on_disk != row["source_sha256"]):
                reasons.append(f"REFERENCE_FILE_CHANGED:{index}:{path.name}")

    if computed_request_sha256 is not None and str(computed_request_sha256) != reviewed:
        if not reasons:
            # The whole-request digest moved but no individual input did: an
            # audio reference, a duration, a parameter — the record still fails.
            reasons.append("REQUEST_DIGEST_CHANGED")

    bound_payload = str((binding or {}).get("payload_sha256") or "").strip()
    if payload_sha is not None and bound_payload and str(payload_sha) != bound_payload:
        reasons.append("PAYLOAD_CHANGED")

    references_missing = [row.get("index") for row in bound_refs.values()
                          if row.get("status") != "PRESENT"]
    return {"status": STATUS_VALID if not reasons else STATUS_INVALID,
            "reasons": reasons, "re_review_required": bool(reasons),
            "request_sha256": reviewed,
            # the reference a reviewer needed but was never given; a coverage gap
            # that no rerun of this check can close
            "references_missing": references_missing,
            "identity_reference_status": (binding or {}).get("identity_reference_status")}


def bind_receipt(binding: dict[str, Any], transaction: dict[str, Any], *,
                 request_path: Any = None, payload_sha: Any = None,
                 bound_at: Any = None) -> dict[str, Any]:
    """Attach the provider's task id to the record that was reviewed.

    The join is by request sha, on both sides: the transaction records the
    semantic digest it POSTed, the record records the review that approved it.
    A receipt for a different request, or a review request whose file has
    changed since it was reviewed, is refused — the record is left untouched.
    """
    binding = dict(binding or {})
    request = binding.get("provider_request") or {}
    reviewed = str(request.get("request_sha256") or "").strip()
    if not reviewed:
        raise ValueError("RECEIPT_BINDING_HAS_NO_REQUEST_SHA: the record carries no reviewed "
                         "request digest, so no receipt can be shown to belong to it")
    transaction_binding = (transaction or {}).get("request_binding") or {}
    sent = str(transaction_binding.get("request_sha256") or "").strip()
    if not sent:
        raise ValueError("RECEIPT_NOT_REQUEST_BOUND: the transaction carries no "
                         "request_binding.request_sha256; bind the review before the POST")
    if sent != reviewed:
        raise ValueError(f"RECEIPT_FOR_ANOTHER_REQUEST: the transaction sent {sent[:16]}, "
                         f"the review bound {reviewed[:16]}")
    if request_path is not None:
        on_disk = sha256_file(Path(str(request_path)))
        declared = str((binding.get("review") or {}).get("request_sha256") or "").strip()
        if on_disk is None:
            raise ValueError(f"REVIEW_REQUEST_MISSING:{request_path}")
        if declared and on_disk != declared:
            raise ValueError("REQUEST_SHA_CHANGED_SINCE_REVIEW: the review request on disk no longer "
                             "hashes to what this record says was reviewed")
    state = str((transaction or {}).get("state") or "")
    task_id = (transaction or {}).get("task_id")
    if not task_id or state != "SUBMITTED_TASK_ID_BOUND":
        raise ValueError(f"TASK_ID_NOT_BOUND:{state or 'NO_STATE'}")

    echo_source = (transaction or {}).get("provider_response") or {}
    echo = {key: echo_source.get(key) for key in
            ("task_id", "request_id", "status", "code", "message")
            if echo_source.get(key) is not None}
    updated = dict(binding)
    updated.update({
        "stage": STAGE_BOUND,
        "task_id": str(task_id),
        "task_id_source": "PROVIDER_RECEIPT_TRANSACTION",
        "bound_at": bound_at or now(),
        "provider_echo": echo,
        "provider_echo_sha256": _sha_bytes(
            json.dumps(echo_source, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")) if echo_source else None,
        "transaction": {
            "submission_fingerprint": (transaction or {}).get("submission_fingerprint"),
            "attempt_id": (transaction or {}).get("attempt_id"),
            "state": state,
        },
        "nulls": {key: value for key, value in (binding.get("nulls") or {}).items()
                  if key not in {"task_id"}},
    })
    transport = [str(value) for value in (transaction or {}).get("sent_reference_sha256") or []]
    rows = [dict(row) for row in updated.get("references") or []]
    if len(transport) == len(rows):
        for row, sha in zip(rows, transport):
            # Transport evidence only: the reviewed digest is over the on-disk shas.
            row["transport_sha256"] = sha
            updated["nulls"].pop(f"references[{row['index']}].transport_sha256", None)
    updated["references"] = rows
    if payload_sha is not None:
        updated["payload_sha256"] = str(payload_sha)
        updated["nulls"].pop("payload_sha256", None)
    return updated


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _stamp(manifest_path: Path, root: Path, out: Path | None) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    stamped = []
    for task in manifest.get("tasks") or []:
        prompt = resolve(task["prompt_file"]).read_text(encoding="utf-8")
        refs = [resolve(p) for p in task.get("reference_images") or []]
        audio = sent_audio_references(task)
        duration = task.get("duration_seconds")
        result = task_request_digest(task, prompt_text=prompt, reference_paths=refs,
                                     duration=int(duration) if duration is not None else None, audio=audio)
        task["reviewed_request_sha256"] = result["request_sha256"]
        stamped.append(task["task_key"])
    (out or manifest_path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    print(json.dumps({"stamped": len(stamped)}, ensure_ascii=False))
    return 0


def _bind_receipt_cli(args: argparse.Namespace) -> int:
    record_path = Path(args.record)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    transaction = json.loads(Path(args.transaction).read_text(encoding="utf-8"))
    binding_key = args.binding_key
    current = record.get(binding_key) or {}
    updated = bind_receipt(current, transaction, request_path=args.request,
                           payload_sha=args.payload_sha)
    if args.dry_run:
        print(json.dumps({"status": "WOULD_BIND", "task_id": updated["task_id"],
                          "stage": updated["stage"]}, ensure_ascii=False))
        return 0
    record[binding_key] = updated
    out = Path(args.out) if args.out else record_path
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "BOUND", "task_id": updated["task_id"],
                      "stage": updated["stage"], "out": str(out)}, ensure_ascii=False))
    return 0


def _verify_cli(args: argparse.Namespace) -> int:
    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    binding = record.get(args.binding_key) or {}
    request_path = args.request or (binding.get("review") or {}).get("request_path")
    report = binding_still_valid(binding, payload_sha=args.payload_sha)
    if request_path and Path(request_path).is_file():
        on_disk = sha256_file(Path(request_path))
        declared = str((binding.get("review") or {}).get("request_sha256") or "")
        if declared and on_disk != declared:
            report["status"] = STATUS_INVALID
            report["reasons"] = [*report["reasons"], "REQUEST_SHA_CHANGED_SINCE_REVIEW"]
            report["re_review_required"] = True
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] in {STATUS_VALID, STATUS_UNENFORCED} else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else __import__("sys").argv[1:])
    if argv and argv[0] in {"stamp", "bind-receipt", "verify"}:
        command, argv = argv[0], argv[1:]
    else:
        command = "stamp"
    parser = argparse.ArgumentParser(
        description="Stamp reviewed_request_sha256, bind a provider receipt to its review record, "
                    "or verify that a binding still describes the same request.")
    sub = parser.add_subparsers(dest="command")
    stamp = sub.add_parser("stamp", help="stamp reviewed_request_sha256 on each task of a manifest")
    stamp.add_argument("--manifest", required=True, type=Path)
    stamp.add_argument("--root", type=Path, default=Path.cwd())
    stamp.add_argument("--out", type=Path, help="defaults to overwriting --manifest")
    bind = sub.add_parser("bind-receipt", help="bind a provider transaction to the reviewed record")
    bind.add_argument("--record", required=True, type=Path)
    bind.add_argument("--transaction", required=True, type=Path)
    bind.add_argument("--request", type=Path, help="the review request file that was answered")
    bind.add_argument("--binding-key", default="request_binding")
    bind.add_argument("--payload-sha", help="sha256 of the body actually POSTed, when known")
    bind.add_argument("--out", type=Path)
    bind.add_argument("--dry-run", action="store_true")
    verify = sub.add_parser("verify", help="is this binding still the reviewed request?")
    verify.add_argument("--record", required=True, type=Path)
    verify.add_argument("--request", type=Path)
    verify.add_argument("--binding-key", default="request_binding")
    verify.add_argument("--payload-sha")
    args = parser.parse_args([command, *argv])

    if args.command == "bind-receipt":
        return _bind_receipt_cli(args)
    if args.command == "verify":
        return _verify_cli(args)
    return _stamp(args.manifest, args.root, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
