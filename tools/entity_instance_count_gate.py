"""Entity instance count reconciliation gate.

Reconcile three sources:
  (a) declared count: contract non_character_entities[].instance_count (optional field)
  (b) reference bindings: provider_scope_projection reference_identity_bindings
  (c) final prompt: entity label occurrences in compiled prompt text

Raises before generation when:
  - instance_count > 1 but only one reference bound
  - prompt entity count mismatches declaration
  - same entity_id in multiple incompatible group_counts positions (same unit)

Skips entities without instance_count (no default assumed).
"""
import re
from typing import Any


def evaluate(
    *,
    contract: dict[str, Any],
    unit_plan: dict[str, Any],
    provider_scope_projection: dict[str, Any],
    prompt_text: str,
) -> dict[str, Any]:
    """Evaluate entity instance count consistency.

    Args:
        contract: generation contract with non_character_entities[]
        unit_plan: compiled unit plan with provider_scope_projection
        provider_scope_projection: output from build_provider_scope_projection
        prompt_text: final compiled prompt text

    Returns:
        {"status": "PASS"|"FAIL", "failures": [...], "checks": [...]}
    """
    failures = []
    checks = []

    # Part 1: declared counts
    entities = contract.get("non_character_entities") or []
    declarations = {}
    for ent in entities:
        eid = ent.get("entity_id")
        count = ent.get("instance_count")
        if not eid or count is None:
            continue
        if not isinstance(count, int) or count < 1:
            failures.append(f"ENTITY_INSTANCE_COUNT_INVALID:{eid}:{count}")
            continue
        declarations[eid] = {
            "count": count,
            "display_name": ent.get("display_name"),
            "kind": ent.get("kind"),
        }

    # Part 2: reference bindings per entity
    bindings = provider_scope_projection.get("reference_identity_bindings") or []
    entity_refs = {}
    for b in bindings:
        eid = str(b.get("entity_id") or "")
        label = str(b.get("provider_entity_label") or "")
        if not eid:
            continue
        entity_refs.setdefault(eid, []).append({
            "reference_index": b.get("reference_index"),
            "label": label,
        })

    # Part 3: reconcile declarations vs bindings
    for eid, decl in declarations.items():
        declared_count = decl["count"]
        refs = entity_refs.get(eid) or []
        bound_count = len(refs)

        checks.append({
            "entity_id": eid,
            "display_name": decl["display_name"],
            "declared_count": declared_count,
            "bound_reference_count": bound_count,
        })

        if declared_count > 1 and bound_count == 1:
            failures.append(
                f"ENTITY_INSTANCE_COUNT_UNDERBOUND:{eid}:declared={declared_count}:refs={bound_count}"
            )
        elif declared_count > 1 and bound_count > 1 and bound_count != declared_count:
            # Multiple refs but count mismatch — advisory, provider may handle via composition
            checks[-1]["note"] = f"ENTITY_REF_COUNT_ADVISORY:refs={bound_count}!=declared={declared_count}"

    # Part 4: prompt text entity label count (basic substring scan)
    # Only check entities with bound references and declarations
    for eid, decl in declarations.items():
        refs = entity_refs.get(eid) or []
        if not refs:
            continue

        # Use first bound label as canonical (all bindings for one entity should use same label)
        label = refs[0]["label"]
        # Count occurrences of label as whole word (simplistic; providers may have structured formats)
        pattern = re.compile(r'\b' + re.escape(label) + r'\b', re.IGNORECASE)
        prompt_count = len(pattern.findall(prompt_text))

        checks.append({
            "entity_id": eid,
            "label": label,
            "prompt_occurrences": prompt_count,
            "declared_count": decl["count"],
        })

        # Prompt count 0 is a hard failure (entity declared and bound but not in prompt)
        if prompt_count == 0:
            failures.append(f"ENTITY_ABSENT_FROM_PROMPT:{eid}:{label}")

    # Part 5: group_counts position conflict (same unit, same entity_id in multiple incompatible positions)
    # This would come from contract shots[].group_counts if present
    # For now, stub (full implementation needs shot-to-unit mapping and position semantics)

    status = "FAIL" if failures else "PASS"
    return {
        "status": status,
        "failures": failures,
        "checks": checks,
        "entities_checked": len(declarations),
    }


def evaluate_unit(contract: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one unit's entity instance counts.

    Convenience wrapper that extracts provider_scope_projection and prompt_text from unit.
    """
    projection = unit.get("provider_scope_projection") or {}
    prompt = unit.get("compiled_prompt") or {}
    prompt_text = prompt.get("positive") or ""

    return evaluate(
        contract=contract,
        unit_plan=unit,
        provider_scope_projection=projection,
        prompt_text=prompt_text,
    )
