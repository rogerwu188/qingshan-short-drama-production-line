from copy import deepcopy

from lines.nalu.runtime.tools.build_keyframe_manifest import cap_non_character_bindings


def test_shared_authority_file_does_not_drop_wardrobe():
    rows = [
        {"role": "subspace_layout", "path": "map.png"},
        {"role": "scene", "path": "map.png"},
        {"role": "character", "path": "face.png"},
        {"role": "character_wardrobe", "path": "costume.png"},
    ]
    original = deepcopy(rows)
    kept, dropped = cap_non_character_bindings(rows, total_limit=3)
    assert kept == original
    assert dropped == []
    assert rows == original


def test_actual_overflow_retains_protected_authorities():
    rows = [
        {"role": "subspace_layout", "path": "map.png"},
        {"role": "scene", "path": "scene.png"},
        {"role": "character", "path": "face.png"},
        {"role": "character_wardrobe", "path": "costume.png"},
    ]
    kept, dropped = cap_non_character_bindings(rows, total_limit=3)
    assert kept == rows[:3]
    assert [row["role"] for row in dropped] == ["character_wardrobe"]
    # The downstream provider-count guard must reject protected overflow;
    # this helper must never silently discard faces or maps to make it fit.
    kept, _ = cap_non_character_bindings(rows[:3], total_limit=2)
    assert kept == rows[:3]


def test_overflow_may_drop_only_explicit_background_identity_after_wardrobe():
    rows = [
        {"role": "subspace_layout", "path": "map.png"},
        {"role": "scene", "path": "scene.png"},
        {"role": "character", "entity_id": "PRIMARY", "path": "primary.png"},
        {"role": "character", "entity_id": "BACKGROUND", "path": "background.png"},
        {"role": "character_wardrobe", "entity_id": "PRIMARY", "path": "primary-costume.png"},
    ]
    kept, dropped = cap_non_character_bindings(
        rows, total_limit=3, optional_character_ids={"BACKGROUND"}
    )
    assert {r["entity_id"] for r in kept if r["role"] == "character"} == {"PRIMARY"}
    assert [r["dropped_reason"] for r in dropped] == ["REFERENCE_TOTAL_MAX_3", "REFERENCE_TOTAL_MAX_3_OPTIONAL_BACKGROUND_IDENTITY"]
