#!/usr/bin/env python3
"""Regression tests for CC_PREGEN_STATE_EVIDENCE_SUPPLEMENT §1–3.

Three fixes from codex feedback 2026-10-17:
1. NONE interaction_mode should not require initiator/target evidence
2. Prop fallback must not fabricate writer_authored or visual PASS
3. Hidden/later props must not require start-frame visual confirmation
"""

import pytest

try:
    from tools.video_physical_continuity_contract import requires_interaction_topology
    from tools.prop_state_contract import compile_prop_states
except ModuleNotFoundError:
    from video_physical_continuity_contract import requires_interaction_topology
    from prop_state_contract import compile_prop_states


class TestInteractionModeNone:
    """§1: NONE mode should opt out of topology requirement even with keywords."""

    def test_none_mode_with_hand_keyword_does_not_require_topology(self):
        unit = {
            "ordered_prompt_specs": [{
                "action": {
                    "interaction_mode": "NONE",
                    "primary_action": "抬手擦汗，独自站立",
                }
            }]
        }
        assert not requires_interaction_topology(unit), \
            "interaction_mode=NONE should opt out even when '抬手' keyword present"

    def test_contact_mode_requires_topology(self):
        unit = {
            "ordered_prompt_specs": [{
                "action": {
                    "interaction_mode": "CONTACT",
                    "primary_action": "推门",
                }
            }]
        }
        assert requires_interaction_topology(unit)

    def test_combat_unit_always_requires_topology(self):
        unit = {
            "combat_or_chase": True,
            "ordered_prompt_specs": [{
                "action": {"interaction_mode": "NONE"}
            }]
        }
        # Combat classification overrides interaction_mode
        assert requires_interaction_topology(unit)


class TestPropFallbackDoesNotFabricateEvidence:
    """§2: Compiler must not invent writer_authored or visual PASS."""

    def test_fallback_does_not_fabricate_authorization(self):
        spec = {
            "action": {
                "start_state": "木盒在桌上",
                "end_state": "木盒打开",
            },
            "props": [{
                "prop_id": "PROP-BOX",
                "binding": "木盒",
            }]
        }
        states, failures = compile_prop_states(spec, source_id="E99-VU-001:BEAT_1")
        # Should materialize entry/exit from action states, but NOT fabricate authorization
        assert len(states) == 1
        state = states[0]
        assert state["entry"]["disposition"] == "木盒在桌上"
        assert state["exit"]["disposition"] == "木盒打开"
        # Authorization should be empty or absent, not compiler-invented
        auth = state.get("transition_authorization") or {}
        assert auth.get("writer_authored") is not True, \
            "Compiler must not fabricate writer_authored from its own fallback"

    def test_fallback_does_not_fabricate_visual_pass(self):
        spec = {
            "action": {"start_state": "持刀站立", "end_state": "刀收鞘"},
            "props": [{"prop_id": "PROP-KNIFE", "binding": "短刀"}]
        }
        states, _ = compile_prop_states(spec, source_id="E99-VU-002:BEAT_1")
        state = states[0]
        visual = state.get("start_frame_visual_confirmation") or {}
        assert visual.get("status") != "PASS" or not visual, \
            "Compiler must not fabricate visual PASS when no evidence exists"


class TestPropVisibilityScopeRespected:
    """§3: Hidden/later props should not fail for missing start-frame evidence."""

    def test_hidden_prop_does_not_require_start_frame_visual(self):
        spec = {
            "action": {},
            "props": [{
                "prop_id": "PROP-HIDDEN",
                "state": {
                    "entry": {"owner": "CHAR-A", "hand": "左", "position": "怀中", "disposition": "藏于衣内"},
                    "exit": {"owner": "CHAR-A", "hand": "左", "position": "掌心", "disposition": "亮出"},
                },
                "visibility_scope": "HIDDEN_UNTIL_ACTION",
                "transition_authorization": {"writer_authored": True, "basis": "原著「暗器」"},
            }]
        }
        # preproduction_only=False: would normally require visual confirmation
        states, failures = compile_prop_states(spec, source_id="E99-VU-003:BEAT_1", preproduction_only=False)
        # Should NOT fail for missing start_frame_visual_confirmation when scope is HIDDEN
        assert all("START_FRAME_PROP_STATE_NOT_VISUALLY_CONFIRMED" not in f for f in failures), \
            f"Hidden prop should not require start-frame visual; got failures: {failures}"

    def test_visible_at_start_prop_requires_visual(self):
        spec = {
            "action": {},
            "props": [{
                "prop_id": "PROP-SWORD",
                "state": {
                    "entry": {"owner": "CHAR-B", "hand": "右", "position": "腰间", "disposition": "剑在鞘中"},
                    "exit": {"owner": "CHAR-B", "hand": "右", "position": "握持", "disposition": "剑已出鞘"},
                },
                "visibility_scope": "VISIBLE_AT_START",
                "transition_authorization": {"writer_authored": True},
            }]
        }
        states, failures = compile_prop_states(spec, source_id="E99-VU-004:BEAT_1", preproduction_only=False)
        # Should fail because VISIBLE_AT_START requires start_frame_visual_confirmation
        assert any("START_FRAME_PROP_STATE_NOT_VISUALLY_CONFIRMED" in f for f in failures), \
            "VISIBLE_AT_START prop without visual confirmation should fail"
