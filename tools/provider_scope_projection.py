#!/usr/bin/env python3
"""Project episode-wide semantics into a provider-visible per-unit allowlist.

The machine contract may retain the complete episode graph.  A provider prompt
may not: noun-rich video models can promote any mentioned entity into pixels or
sound.  This module makes that boundary explicit and independently auditable.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any


SCHEMA = "qingshan.provider_scope_projection.v1"
ACTIVE_FROM_EPISODE = 56
NEGATIVE_HEADERS = ("negative_constraints:", "NEGATIVE_PROMPT:", "【负面", "【限制")

# --------------------------------------------------------------------------- #
# Provider prompt modes: one canonical vocabulary
# --------------------------------------------------------------------------- #
# The projection, the image presubmit gate and the video submitter each grew a
# different spelling of the same flag (`provider_scope_prompt_mode`,
# `scope_mode`, `h3_prompt_profile`) with a different suffix
# (MACHINE_GRAPH_ONLY / MACHINE_ROLE_GRAPH_ONLY / H3_..._V1).  A change in one
# therefore never reached the other two.  Every caller now normalizes through
# this table, so the three spellings still in flight keep working.
PROMPT_MODE_SINGLE_SUBJECT = "POSITIVE_SINGLE_SUBJECT_MACHINE_GRAPH_ONLY"
PROMPT_MODE_TIGHT_POV_SINGLE_SUBJECT = "POSITIVE_SINGLE_SUBJECT_TIGHT_POV_MACHINE_GRAPH_ONLY"
SINGLE_SUBJECT_PROMPT_MODES = (
    PROMPT_MODE_SINGLE_SUBJECT,
    PROMPT_MODE_TIGHT_POV_SINGLE_SUBJECT,
)
PROMPT_MODE_ALIASES = {
    "POSITIVE_SINGLE_SUBJECT_MACHINE_ROLE_GRAPH_ONLY": PROMPT_MODE_SINGLE_SUBJECT,
    "POSITIVE_SINGLE_SUBJECT_MACHINE_GRAPH_ONLY": PROMPT_MODE_SINGLE_SUBJECT,
    "POSITIVE_SINGLE_SUBJECT_TIGHT_POV_MACHINE_ROLE_GRAPH_ONLY": PROMPT_MODE_TIGHT_POV_SINGLE_SUBJECT,
    "POSITIVE_SINGLE_SUBJECT_TIGHT_POV_MACHINE_GRAPH_ONLY": PROMPT_MODE_TIGHT_POV_SINGLE_SUBJECT,
    "POSITIVE_SINGLE_SUBJECT": PROMPT_MODE_SINGLE_SUBJECT,
    "H3_POSITIVE_SINGLE_SUBJECT_V1": PROMPT_MODE_SINGLE_SUBJECT,
    "H3_TIGHT_POV_SINGLE_SUBJECT_V1": PROMPT_MODE_TIGHT_POV_SINGLE_SUBJECT,
}

# Reference roles the projection may carry.  Identity roles own a face; every
# other role binds geometry, a location or a prop and must not be able to
# claim identity ownership.
REFERENCE_ROLE_SEMANTICS_V2 = "IDENTITY_OWNER_FROM_ROLE_V2"
IDENTITY_BINDING_ROLES = frozenset({"IDENTITY", "CHARACTER", "CHARACTER_REFERENCE", "SPEAKER"})
PROP_BINDING_ROLES = frozenset({"PROP", "PROP_REFERENCE", "OBJECT", "OBJECT_REFERENCE"})
NON_IDENTITY_BINDING_ROLES = frozenset({
    "SCENE", "LOCATION", "SPACE_MAP", "GLOBAL_SPACE_MAP", "EPISODE_GLOBAL_SPACE_MAP",
    "SUBSPACE_LAYOUT", "GEOMETRY", "REFERENCE",
})


def normalize_prompt_mode(value: Any) -> str:
    """Map any in-flight spelling of the single-subject flag onto one value.

    An unrecognized value is returned uppercased unchanged: a mode this table
    does not know must stay distinguishable rather than silently collapse onto
    the single-subject mode.
    """
    text = str(value or "").strip().upper()
    if not text:
        return ""
    return PROMPT_MODE_ALIASES.get(text, text)


def is_single_subject_mode(value: Any) -> bool:
    return normalize_prompt_mode(value) in SINGLE_SUBJECT_PROMPT_MODES


def is_tight_pov_mode(value: Any) -> bool:
    return normalize_prompt_mode(value) == PROMPT_MODE_TIGHT_POV_SINGLE_SUBJECT


def binding_role_for(entity_id: str, role: Any = None) -> str:
    """Classify one reference binding as identity / prop / non-identity.

    An explicit role wins; otherwise the machine id namespace decides.  The
    fallback keeps projections built before roles were recorded working.
    """
    declared = str(role or "").strip().upper().replace(" ", "_")
    if declared in IDENTITY_BINDING_ROLES:
        return "IDENTITY"
    if declared in PROP_BINDING_ROLES:
        return "PROP"
    if declared in NON_IDENTITY_BINDING_ROLES:
        return "NON_IDENTITY"
    entity = str(entity_id or "").strip().upper()
    if entity.startswith("CHAR-"):
        return "IDENTITY"
    # SET- is a set piece (build_episode_asset_requirements is_set_piece): bound as a prop plate at S5, so it
    # must not fall through to IDENTITY (urban lab E01 2026-10-23: SET-DESK failed every keyframe precheck)
    if entity.startswith(("PROP-", "OBJ-", "SET-")):
        return "PROP"
    # EGSM- is the per-episode global space map (nalu, e.g. EGSM-AQ-E04); it was falling through to
    # IDENTITY and failed every keyframe of 401286 《阿Q正传》 E04 (2026-10-16)
    if entity.startswith(("GSM-", "EGSM-", "LOC-", "SUBSPACE-", "ROOM-", "ZONE-", "FIXED-", "ANGLE-")):
        return "NON_IDENTITY"
    return "IDENTITY"


# Identity tiers a character catalog row may declare.  Only NAMED roles carry a
# face that must be reproduced exactly; the other two may appear on screen but
# are not identity-gated.  Without this tier a walk-on had exactly one possible
# destination — the forbidden-absent list — so a scripted innkeeper or a street
# full of passers-by could only ever be expressed as a term the prompt must not
# contain.
IDENTITY_TIERS = frozenset({"NAMED", "ANONYMOUS_FUNCTIONAL", "BACKGROUND_CROWD"})
DEFAULT_IDENTITY_TIER = "NAMED"


def identity_tier_for(row: dict[str, Any]) -> str:
    declared = str(row.get("identity_tier") or row.get("role_tier") or "").strip().upper()
    if declared in IDENTITY_TIERS:
        return declared
    if row.get("anonymous_role") is True or row.get("functional_role") is True:
        return "ANONYMOUS_FUNCTIONAL"
    if row.get("background_crowd") is True:
        return "BACKGROUND_CROWD"
    return DEFAULT_IDENTITY_TIER


def _positive_prompt(text: str) -> str:
    positions = [text.find(value) for value in NEGATIVE_HEADERS if text.find(value) >= 0]
    return text[: min(positions)] if positions else text


# --------------------------------------------------------------------------- #
# Shared prompt clauses: the renderer writes them, the gate looks for them
# --------------------------------------------------------------------------- #
# Both sides used to spell these sentences out separately, so the gate could
# only ever find the exact string the renderer happened to emit.  One builder
# per clause means they cannot drift.
def population_clause_core(
    total: int,
    *,
    background_population_count: int = 0,
    unbound_visible_living_entity_count: int = 0,
    anonymous_role_descriptors: list[str] | None = None,
) -> str:
    """The countable part of the population sentence.

    A prompt is valid when it states this; the leading "only bound identities
    are visible" framing is the renderer's own and is not required, so prompts
    written before it existed still validate.
    """
    clause = (
        f"render exactly {int(total)} living entity instances in total; "
        f"background population count={int(background_population_count)}; "
        f"unbound living entity count={int(unbound_visible_living_entity_count)}"
    )
    descriptors = [str(value).strip() for value in anonymous_role_descriptors or [] if str(value).strip()]
    if descriptors:
        clause += "; declared anonymous walk-on roles: " + ", ".join(descriptors)
    return clause


def population_clause(
    total: int,
    *,
    background_population_count: int = 0,
    unbound_visible_living_entity_count: int = 0,
    anonymous_role_descriptors: list[str] | None = None,
) -> str:
    """The full clause the H3 renderer emits."""
    return "Only bound identities are visible; " + population_clause_core(
        total,
        background_population_count=background_population_count,
        unbound_visible_living_entity_count=unbound_visible_living_entity_count,
        anonymous_role_descriptors=anonymous_role_descriptors,
    )


def instance_cardinality_clauses(label: str, count: int = 1) -> tuple[str, ...]:
    """Every per-entity instance sentence a valid prompt may carry.

    ``count == 1`` accepts both historical wordings: the scoped renderer emits
    "at most one" (a bound identity that the beat may keep out of frame) and the
    unscoped one emits "exactly one".  A count above one has exactly one
    acceptable wording, because no older prompt could have expressed it.
    """
    label = str(label)
    if int(count) == 1:
        return (
            f"render exactly one visible instance of {label}",
            f"render at most one visible instance of {label}",
        )
    return (f"render exactly {int(count)} visible instances of {label}",)


def positive_single_subject_composition_clause(tight_pov: bool) -> str:
    """The composition sentence, in the casing the renderer has always emitted."""
    return (
        "SUBJECT_1 fills a tight head-and-shoulders point-of-view close-up as the single human figure"
        if tight_pov
        else "SUBJECT_1 fills the composed medium frame as its single human figure"
    )


def build_provider_scope_projection(
    *,
    visible_character_ids: list[str],
    visible_prop_ids: list[str],
    episode_character_catalog: list[dict[str, Any]],
    episode_prop_catalog: list[dict[str, Any]] | None = None,
    reference_images: list[dict[str, Any]] | None = None,
    scene_domain: str,
    location_ids: list[str] | None = None,
    environment_terms: list[str] | None = None,
    sound_terms: list[str] | None = None,
    visible_entity_instance_counts: dict[str, int] | None = None,
    anonymous_role_descriptors: list[str] | None = None,
    background_population_count: int | None = None,
    unbound_visible_living_entity_count: int | None = None,
    provider_scope_prompt_mode: str | None = None,
    reference_role_semantics: str | None = None,
) -> dict[str, Any]:
    """Project one unit's provider-visible scope.

    Every parameter below ``sound_terms`` is optional and defaults to the
    historical behavior, so callers that predate instance counts keep producing
    the same projection.  ``visible_entity_instance_counts`` lets a unit say a
    crowd entity is really N instances; ``background_population_count`` lets it
    declare anonymous walk-ons instead of the literal zero that used to make a
    scripted street scene fail the gate.
    """
    visible = set(visible_character_ids)
    refs = reference_images or []
    role_semantics = str(reference_role_semantics or REFERENCE_ROLE_SEMANTICS_V2)
    bindings = []
    for index, row in enumerate(refs, 1):
        entity_id = str(row.get("entity_id") or "")
        if not entity_id:
            continue
        declared_role = str(row.get("role") or "").strip().upper() or None
        binding_role = binding_role_for(entity_id, declared_role)
        binding: dict[str, Any] = {
            "reference_index": index,
            "entity_id": entity_id,
            "provider_entity_label": str(row.get("provider_entity_label") or entity_id),
            "role": declared_role,
            "binding_role": binding_role,
            "exclusive_identity_owner": True,
        }
        if binding_role != "IDENTITY":
            # A geometry / location / prop plate conveys no face.  Claiming
            # exclusive identity ownership for it is what let a misplaced
            # reference pass every check that existed.
            binding["exclusive_identity_owner"] = False
            binding["may_define_identity"] = False
            bindings.append(binding)
            continue
        binding["may_define_identity"] = True
        bindings.append(binding)
    # The v4 contract can expose a character under a machine id while the
    # provider prompt uses its canonical/display name (or an alias).  Build
    # the visible label set first so those aliases are not misclassified as
    # absent episode entities.  Without this, a visible 白鲤郡主 row can also
    # be emitted as an absent 白鲤 row and the prompt gate rejects a valid
    # single-scene cast.
    visible_labels: set[str] = set()
    for row in episode_character_catalog:
        entity_id = str(row.get("character_id") or row.get("entity_id") or "")
        row_labels = {
            value for value in [
                str(row.get("canonical_name") or "").strip(),
                str(row.get("provider_entity_label") or "").strip(),
                *[str(value).strip() for value in row.get("aliases") or []],
            ] if value
        }
        # v4 grouped plans may carry authored display names in cast while
        # the episode catalog carries machine ids.  Treat either namespace as
        # the same visible entity for alias/absent-term projection.
        if entity_id not in visible and not (row_labels & visible):
            continue
        visible_labels.update(
            row_labels
        )
    absent = []
    for row in episode_character_catalog:
        entity_id = str(row.get("character_id") or row.get("entity_id") or "")
        if not entity_id or entity_id in visible:
            continue
        terms = [
            str(row.get("canonical_name") or "").strip(),
            str(row.get("provider_entity_label") or "").strip(),
            *[str(value).strip() for value in row.get("aliases") or []],
        ]
        # Do not forbid a display-name/alias that belongs to a visible
        # machine entity.  This is an identity-namespace compatibility rule,
        # not a change to the episode cast or provider prompt.
        if any(term and term in visible_labels for term in terms):
            continue
        absent.append({"entity_id": entity_id, "forbidden_positive_terms": [v for v in dict.fromkeys(terms) if v]})
    # A walk-on the script calls for is not an absent entity: it has no face to
    # reproduce, but it is allowed on screen.  Its labels leave the forbidden
    # list and become descriptors the prompt may name.
    anonymous_terms: list[str] = []
    for row in episode_character_catalog:
        if identity_tier_for(row) == "NAMED":
            continue
        entity_id = str(row.get("character_id") or row.get("entity_id") or "")
        tier_terms = [
            str(row.get("provider_entity_label") or "").strip(),
            str(row.get("canonical_name") or "").strip(),
            *[str(value).strip() for value in row.get("aliases") or []],
            *[str(value).strip() for value in row.get("anonymous_role_descriptors") or []],
        ]
        tier_terms = [term for term in tier_terms if term]
        if not entity_id or not tier_terms:
            continue
        # Both namespaces: the row is visible, or one of its labels is.
        if entity_id not in visible and not (set(tier_terms) & visible_labels):
            continue
        absent = [entry for entry in absent if entry["entity_id"] != entity_id]
        for value in tier_terms:
            if value not in anonymous_terms:
                anonymous_terms.append(value)
    resolved_anonymous = [
        str(value).strip()
        for value in [*(anonymous_role_descriptors or []), *anonymous_terms]
        if str(value).strip()
    ]
    # Instance counts default to one per visible entity (historical behavior).
    counts: dict[str, int] = {entity_id: 1 for entity_id in sorted(visible)}
    for entity_id, value in (visible_entity_instance_counts or {}).items():
        key = str(entity_id)
        if key not in counts:
            # A count for an entity that is not in the visible set is a caller
            # bug: it would fabricate provider-visible instances.
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed < 1:
            continue
        counts[key] = parsed
    resolved_background = 0 if background_population_count is None else int(background_population_count)
    resolved_unbound = (
        resolved_background
        if unbound_visible_living_entity_count is None
        else int(unbound_visible_living_entity_count)
    )
    return {
        "schema": SCHEMA,
        "status": "LOCKED",
        "scene_domain": scene_domain,
        "visible_character_ids": sorted(visible),
        "visible_entity_instance_counts": counts,
        "exclusive_visible_living_entity_set": True,
        "visible_living_entity_instance_total": sum(counts.values()),
        "background_population_count": resolved_background,
        "unbound_visible_living_entity_count": resolved_unbound,
        "anonymous_role_descriptors": resolved_anonymous,
        "reference_role_semantics": role_semantics,
        "visible_prop_ids": sorted(set(visible_prop_ids)),
        "location_ids": sorted(set(location_ids or [])),
        "environment_terms": list(dict.fromkeys(environment_terms or [])),
        "sound_terms": list(dict.fromkeys(sound_terms or [])),
        "reference_identity_bindings": bindings,
        "absent_episode_entities": absent,
        "episode_prop_catalog": deepcopy(episode_prop_catalog or []),
        "provider_reads_episode_global_contract_directly": False,
    }


def validate_provider_scope_projection(
    payload: dict[str, Any], *, prompt_text: str | None = None, model: str | None = None,
) -> dict[str, Any]:
    projection = payload.get("provider_scope_projection")
    if not isinstance(projection, dict):
        identity = str(payload.get("episode") or payload.get("unit_id") or "").upper()
        match = re.search(r"(?:^|[^A-Z])E(\d+)", identity)
        required = bool(
            match
            and int(match.group(1)) >= ACTIVE_FROM_EPISODE
            and str(model or payload.get("model") or "").strip().lower()
            in {
                "minimax-h3", "h3", "seedance-2.0-pro", "gpt-image-2-pro",
                "sd2", "stable-diffusion-2", "seed", "seed-image",
                "nano-banana", "nanobanana", "nanubanner", "google-nano-banana",
            }
        )
        failures = ["PROVIDER_SCOPE_PROJECTION_MISSING"] if required else []
        return {
            "schema": "qingshan.provider_scope_projection_gate.v1",
            "status": "FAIL" if failures else "NOT_APPLICABLE",
            "required": required,
            "failures": failures,
        }
    failures: list[str] = []
    if projection.get("schema") != SCHEMA:
        failures.append("PROVIDER_SCOPE_SCHEMA_INVALID")
    if projection.get("status") != "LOCKED":
        failures.append("PROVIDER_SCOPE_NOT_LOCKED")
    if projection.get("provider_reads_episode_global_contract_directly") is not False:
        failures.append("PROVIDER_SCOPE_GLOBAL_CONTRACT_ACCESS_NOT_DISABLED")
    visible = [str(value) for value in projection.get("visible_character_ids") or []]
    if len(visible) != len(set(visible)):
        failures.append("PROVIDER_SCOPE_DUPLICATE_VISIBLE_ENTITY")
    counts = projection.get("visible_entity_instance_counts") or {}
    if set(map(str, counts)) != set(visible):
        failures.append("PROVIDER_SCOPE_VISIBLE_INSTANCE_CARDINALITY_INVALID")
    else:
        for entity_id in visible:
            try:
                value = int(counts.get(entity_id))
            except (TypeError, ValueError):
                failures.append("PROVIDER_SCOPE_VISIBLE_INSTANCE_CARDINALITY_INVALID:" + entity_id)
                continue
            if value < 1:
                failures.append("PROVIDER_SCOPE_VISIBLE_INSTANCE_CARDINALITY_INVALID:" + entity_id)
    if projection.get("exclusive_visible_living_entity_set") is not True:
        failures.append("PROVIDER_SCOPE_VISIBLE_SET_NOT_EXCLUSIVE")
    declared_total = projection.get("visible_living_entity_instance_total")
    background = projection.get("background_population_count")
    unbound = projection.get("unbound_visible_living_entity_count")
    if declared_total != sum(counts.values()):
        failures.append("PROVIDER_SCOPE_VISIBLE_TOTAL_INVALID")
    # The projection has to name its own background population so the prompt
    # clause and the gate agree on a number.  Historically both were hardcoded
    # zero, which made a scripted crowd unrepresentable *and* unfalsifiable.
    if not isinstance(background, int) or isinstance(background, bool) or background < 0:
        failures.append("PROVIDER_SCOPE_BACKGROUND_POPULATION_INVALID")
    if not isinstance(unbound, int) or isinstance(unbound, bool) or unbound < 0:
        failures.append("PROVIDER_SCOPE_UNBOUND_LIVING_ENTITY_INVALID")
    if isinstance(background, int) and isinstance(unbound, int) and unbound < background:
        failures.append("PROVIDER_SCOPE_UNBOUND_BELOW_BACKGROUND")
    bindings = projection.get("reference_identity_bindings") or []
    indices = [row.get("reference_index") for row in bindings]
    entities = [str(row.get("entity_id") or "") for row in bindings]
    if len(indices) != len(set(indices)) or len(entities) != len(set(entities)):
        failures.append("PROVIDER_SCOPE_REFERENCE_BINDING_NOT_ONE_TO_ONE")
    for row in bindings:
        entity_id = str(row.get("entity_id") or "")
        role = str(row.get("role") or "").strip().upper() or None
        binding_role = str(row.get("binding_role") or "") or binding_role_for(entity_id, role)
        if binding_role == "IDENTITY":
            if row.get("exclusive_identity_owner") is not True:
                failures.append("PROVIDER_SCOPE_REFERENCE_OWNER_NOT_EXCLUSIVE:" + entity_id)
            if str(row.get("entity_id") or "") not in visible:
                failures.append("PROVIDER_SCOPE_REFERENCE_ENTITY_NOT_VISIBLE:" + entity_id)
        else:
            # Non-identity plates bind geometry, a location or a prop.  They may
            # still be legitimate, but they must not claim a face.
            if row.get("exclusive_identity_owner") is True and row.get("may_define_identity") is not False:
                failures.append(
                    "PROVIDER_SCOPE_NONIDENTITY_REFERENCE_CLAIMS_IDENTITY_OWNER:" + entity_id
                )
    episode_no = re.search(r"(?:^|[^A-Z])E(\d+)", str(payload.get("episode") or payload.get("unit_id") or "").upper())
    # a payload that names no episode (unit tests, ad-hoc compiles) gets the full contract
    prompt_checks_active = (episode_no is None) or int(episode_no.group(1)) >= ACTIVE_FROM_EPISODE
    # ACTIVE_FROM_EPISODE alone left an episode below the constant with no way in:
    # the switch was a source edit, not a contract field.  An explicit declaration
    # on the payload or projection now turns the same checks on for one episode
    # without moving the constant for every older one.
    declared_checks = str(
        payload.get("provider_scope_prompt_checks")
        or projection.get("provider_scope_prompt_checks")
        or ""
    ).strip().upper()
    if declared_checks in {"ENFORCED", "ON", "TRUE"}:
        prompt_checks_active = True
    elif declared_checks in {"DISABLED", "OFF", "FALSE"}:
        prompt_checks_active = False
    if prompt_text is not None and prompt_checks_active:
        # 2026-09-20 (nalu line): these prompt-text checks are part of the projection contract that
        # ACTIVE_FROM_EPISODE governs.  compile_grouped_seedance_manifest.py began attaching a
        # projection to every compiled unit today, which switched them on for episodes the contract
        # never covered (E08's handoff line quotes the previous shot's completion state and so names
        # the character who acted last).  Episodes at or above ACTIVE_FROM_EPISODE are unaffected.
        # H3 can promote concrete nouns even from a negative clause, so absent
        # episode entities are forbidden across its entire provider text. SD2
        # retains its established negative-prompt behavior and is checked only
        # on the positive portion.
        positive = (
            prompt_text.casefold()
            if str(model or payload.get("model") or "").strip().lower() in {"minimax-h3", "h3"}
            else _positive_prompt(prompt_text).casefold()
        )
        # A dialogue listener may be named in the machine prompt while being
        # intentionally off-screen.  That semantic reference is not a visual
        # cast admission and must not trip the absent-entity visual gate.
        dialogue_context_terms: set[str] = set()
        for spec in payload.get("ordered_prompt_specs") or []:
            role = spec.get("role_semantic_disambiguation") or {}
            listener_id = str(role.get("dialogue_listener_id") or "")
            if not listener_id:
                continue
            for catalog_row in payload.get("character_entities") or []:
                cid = str(catalog_row.get("character_id") or catalog_row.get("entity_id") or "")
                if cid == listener_id:
                    dialogue_context_terms.update(
                        value for value in [
                            str(catalog_row.get("canonical_name") or "").strip(),
                            *[str(value).strip() for value in catalog_row.get("aliases") or []],
                        ] if value
                    )
        # Transition/state contracts are machine continuity metadata.  Their
        # prior/next-shot names may legitimately occur in the serialized
        # prompt, but they do not authorize a new provider-visible person.
        continuity_context = json.dumps(
            {"transition": payload.get("transition_contract"),
             "internal": payload.get("internal_transition_contracts"),
             "state": payload.get("start_frame_semantic_contract")},
            ensure_ascii=False,
        )
        for row in projection.get("absent_episode_entities") or []:
            for term in row.get("forbidden_positive_terms") or []:
                token = str(term).strip()
                if len(token) < 2:
                    continue
                if token in dialogue_context_terms:
                    continue
                if token in continuity_context:
                    continue
                if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(token.casefold()) + r"(?![A-Za-z0-9_-])", positive):
                    failures.append(
                        "PROVIDER_SCOPE_ABSENT_ENTITY_IN_POSITIVE_PROMPT:"
                        + str(row.get("entity_id") or "UNKNOWN") + ":" + token
                    )
        if str(model or payload.get("model") or "").strip().lower() in {"minimax-h3", "h3"}:
            prompt_mode = projection.get("provider_scope_prompt_mode")
            positive_single_subject = is_single_subject_mode(prompt_mode)
            tight_pov_single_subject = is_tight_pov_mode(prompt_mode)
            for row in bindings:
                entity_id = str(row.get("entity_id") or "")
                is_identity = (
                    str(row.get("binding_role") or "")
                    or binding_role_for(entity_id, row.get("role"))
                ) == "IDENTITY"
                marker = f"@Image{row['reference_index']}:".casefold()
                label = str(row.get("provider_entity_label") or "").casefold()
                if marker not in positive or not label or label not in positive:
                    failures.append("H3_PROVIDER_SCOPE_REFERENCE_MAPPING_MISSING:" + str(row.get("entity_id") or "UNKNOWN"))
                if not is_identity:
                    # A plate bound to geometry, a location or a prop still has
                    # to declare itself, but it carries no face: the subject and
                    # cardinality clauses below are identity-only.
                    continue
                if positive_single_subject:
                    if len(visible) != 1 or len(bindings) != 1:
                        failures.append("H3_POSITIVE_SINGLE_SUBJECT_CARDINALITY_INVALID")
                    if f"{label} is subject_1" not in positive:
                        failures.append("H3_POSITIVE_SINGLE_SUBJECT_REFERENCE_MAPPING_MISSING:" + str(row.get("entity_id") or "UNKNOWN"))
                else:
                    expected_count = counts.get(str(row.get("entity_id") or ""), 1)
                    accepted = [
                        clause.casefold()
                        for clause in instance_cardinality_clauses(label, expected_count)
                    ]
                    if not any(clause in positive for clause in accepted):
                        failures.append("H3_PROVIDER_SCOPE_INSTANCE_CARDINALITY_MISSING:" + str(row.get("entity_id") or "UNKNOWN"))
            total = int(projection.get("visible_living_entity_instance_total") or 0)
            if positive_single_subject:
                required_composition = positive_single_subject_composition_clause(tight_pov_single_subject).casefold()
                if required_composition not in positive:
                    failures.append("H3_POSITIVE_SINGLE_SUBJECT_COMPOSITION_CLAUSE_MISSING")
            else:
                required_population_clause = population_clause_core(
                    total,
                    background_population_count=background if isinstance(background, int) else 0,
                    unbound_visible_living_entity_count=unbound if isinstance(unbound, int) else 0,
                    anonymous_role_descriptors=projection.get("anonymous_role_descriptors") or [],
                ).casefold()
                if required_population_clause not in positive:
                    failures.append("H3_PROVIDER_SCOPE_EXCLUSIVE_POPULATION_CLAUSE_MISSING")
    return {
        "schema": "qingshan.provider_scope_projection_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "required": True,
        "failures": failures,
    }
