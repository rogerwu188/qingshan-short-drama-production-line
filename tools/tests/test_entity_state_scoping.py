from lines.nalu.runtime.tools.adapt_v4_layers_to_runtime import derive_entity_states


def test_only_subject_receives_primary_frame_state():
    states = derive_entity_states(["A", "B", "C"], "A", "A points at the door")
    assert states["A"] == "A points at the door"
    assert states["B"] != states["A"]
    assert states["C"] != states["A"]
    assert "不执行主动作" in states["B"]


def test_authored_per_entity_state_wins_without_spillover():
    states = derive_entity_states(
        ["A", "B"], "A", "A points", {"B": "B listens with hands folded"}
    )
    assert states == {"A": "A points", "B": "B listens with hands folded"}
