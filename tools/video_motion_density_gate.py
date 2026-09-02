#!/usr/bin/env python3
"""Model-neutral alias for the shared motion/state-delta gate.

The implementation originated in the SD2 audit but is deliberately shared by
SD2 and H3.  Keep the legacy import path working while callers migrate.
"""

try:
    from tools.sd2_motion_density_gate import (  # noqa: F401
        EXTEND_WORDS,
        IMPULSE_VERBS,
        POLICY_VERSION,
        STATE_DELTA_DIMENSIONS,
        extend_word_hits,
        impulse_verb_hits,
        validate_combat_causal_chain,
        validate_combat_impulse,
        validate_execution_plan,
        validate_state_delta,
    )
except ModuleNotFoundError:
    from sd2_motion_density_gate import (  # noqa: F401
        EXTEND_WORDS,
        IMPULSE_VERBS,
        POLICY_VERSION,
        STATE_DELTA_DIMENSIONS,
        extend_word_hits,
        impulse_verb_hits,
        validate_combat_causal_chain,
        validate_combat_impulse,
        validate_execution_plan,
        validate_state_delta,
    )


__all__ = [
    "EXTEND_WORDS",
    "IMPULSE_VERBS",
    "POLICY_VERSION",
    "STATE_DELTA_DIMENSIONS",
    "extend_word_hits",
    "impulse_verb_hits",
    "validate_combat_causal_chain",
    "validate_combat_impulse",
    "validate_execution_plan",
    "validate_state_delta",
]
