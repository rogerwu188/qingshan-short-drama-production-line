"""Regression tests for the pre-generation consistency and retry-loop fixes.

Every test here is free: no provider call, no credential, no paid stage.  They
exist because each defect below shipped with the mechanism that would have
caught it either missing or unreachable — a hardcoded constant, an unread
policy key, a gate whose input no code produced, and a validation chain that
lived only in a function nothing called.  The theme is agreement between two
places that were supposed to say the same thing.
"""

import unittest

from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.provider_scope_projection import (
    ACTIVE_FROM_EPISODE,
    PROMPT_MODE_ALIASES,
    PROMPT_MODE_SINGLE_SUBJECT,
    PROMPT_MODE_TIGHT_POV_SINGLE_SUBJECT,
    REFERENCE_ROLE_SEMANTICS_V2,
    binding_role_for,
    build_provider_scope_projection,
    instance_cardinality_clauses,
    is_single_subject_mode,
    is_tight_pov_mode,
    normalize_prompt_mode,
    population_clause,
    population_clause_core,
    validate_provider_scope_projection,
)
from tools.reroll_cost_guard import reroll_number_for, record_reroll_event
from tools.retry_cap_gate import validate_submission_attempt
from tools.shot_media_admission_gate import precheck_submission_inputs, validate_retry_change
from tools.submit_giggle_video_manifest_v2 import validate_task_submission_gates


class PopulationDeclarableTest(unittest.TestCase):
    """1 — a scripted crowd must be expressible, and declared, not assumed."""

    def test_background_population_is_declarable_not_hardcoded_zero(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[
                {"character_id": "CHAR-A", "canonical_name": "A"},
            ],
            scene_domain="STREET",
            background_population_count=4,
        )
        self.assertEqual(projection["background_population_count"], 4)
        self.assertEqual(projection["unbound_visible_living_entity_count"], 4)

    def test_undeclared_population_still_defaults_to_zero(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-A", "canonical_name": "A"}],
            scene_domain="STREET",
        )
        self.assertEqual(projection["background_population_count"], 0)
        self.assertEqual(projection["visible_living_entity_instance_total"], 1)


class InstanceCountTest(unittest.TestCase):
    """2 — an entity with several instances must be countable."""

    def test_declared_instance_count_reaches_total(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-GUARD"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-GUARD", "canonical_name": "Guard"}],
            scene_domain="GATE",
            visible_entity_instance_counts={"CHAR-GUARD": 3},
        )
        self.assertEqual(projection["visible_entity_instance_counts"], {"CHAR-GUARD": 3})
        self.assertEqual(projection["visible_living_entity_instance_total"], 3)

    def test_count_for_invisible_entity_is_ignored(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-GUARD"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-GUARD", "canonical_name": "Guard"}],
            scene_domain="GATE",
            visible_entity_instance_counts={"CHAR-GUARD": 1, "CHAR-GHOST": 9},
        )
        self.assertNotIn("CHAR-GHOST", projection["visible_entity_instance_counts"])

    def test_instance_count_above_one_has_one_acceptable_wording(self):
        self.assertEqual(
            instance_cardinality_clauses("Guard", 3),
            ("render exactly 3 visible instances of Guard",),
        )

    def test_count_one_keeps_both_historical_wordings(self):
        self.assertEqual(
            sorted(instance_cardinality_clauses("Guard", 1)),
            sorted([
                "render exactly one visible instance of Guard",
                "render at most one visible instance of Guard",
            ]),
        )


class PromptModeVocabularyTest(unittest.TestCase):
    """3 — one flag, three historical spellings, one meaning."""

    def test_all_known_spellings_normalize_together(self):
        for spelling in (
            "POSITIVE_SINGLE_SUBJECT_MACHINE_ROLE_GRAPH_ONLY",
            "POSITIVE_SINGLE_SUBJECT_MACHINE_GRAPH_ONLY",
            "H3_POSITIVE_SINGLE_SUBJECT_V1",
            "POSITIVE_SINGLE_SUBJECT",
        ):
            self.assertEqual(normalize_prompt_mode(spelling), PROMPT_MODE_SINGLE_SUBJECT)
            self.assertTrue(is_single_subject_mode(spelling), spelling)

    def test_tight_pov_is_not_the_plain_single_subject_mode(self):
        self.assertTrue(is_tight_pov_mode("POSITIVE_SINGLE_SUBJECT_TIGHT_POV_MACHINE_ROLE_GRAPH_ONLY"))
        self.assertFalse(is_single_subject_mode(""))

    def test_unknown_mode_is_not_silently_single_subject(self):
        self.assertEqual(normalize_prompt_mode("SOME_FUTURE_MODE"), "SOME_FUTURE_MODE")
        self.assertFalse(is_single_subject_mode("SOME_FUTURE_MODE"))


class ReferenceRoleSemanticsTest(unittest.TestCase):
    """4 — a geometry or prop plate must not be able to claim a face."""

    def test_role_and_namespace_decide_identity_ownership(self):
        self.assertEqual(binding_role_for("CHAR-A", None), "IDENTITY")
        self.assertEqual(binding_role_for("PROP-DEER", None), "PROP")
        self.assertEqual(binding_role_for("GSM-TOWN", None), "NON_IDENTITY")
        self.assertEqual(binding_role_for("CHAR-A", "SCENE"), "NON_IDENTITY")

    def test_non_identity_plate_does_not_claim_identity_owner(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-A", "canonical_name": "A"}],
            scene_domain="STREET",
            reference_images=[
                {"entity_id": "CHAR-A", "role": "IDENTITY", "provider_entity_label": "A"},
                {"entity_id": "GSM-TOWN", "role": "SCENE", "provider_entity_label": "town map"},
            ],
        )
        by_entity = {row["entity_id"]: row for row in projection["reference_identity_bindings"]}
        self.assertTrue(by_entity["CHAR-A"]["exclusive_identity_owner"])
        self.assertFalse(by_entity["GSM-TOWN"]["exclusive_identity_owner"])
        self.assertFalse(by_entity["GSM-TOWN"]["may_define_identity"])
        self.assertEqual(projection["reference_role_semantics"], REFERENCE_ROLE_SEMANTICS_V2)

    def test_projection_with_non_identity_plate_validates(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-A", "canonical_name": "A"}],
            scene_domain="STREET",
            reference_images=[
                {"entity_id": "CHAR-A", "role": "IDENTITY", "provider_entity_label": "A"},
                {"entity_id": "GSM-TOWN", "role": "SCENE", "provider_entity_label": "town map"},
            ],
        )
        report = validate_provider_scope_projection({"provider_scope_projection": projection})
        self.assertEqual(report["status"], "PASS", report["failures"])


class ProjectionGateDeclaredFieldTest(unittest.TestCase):
    """5 — the validator must reject a projection that never declared itself."""

    def _projection(self, **overrides):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-A", "canonical_name": "A"}],
            scene_domain="STREET",
        )
        projection.update(overrides)
        return {"provider_scope_projection": projection}

    def test_missing_background_field_is_invalid_not_assumed_zero(self):
        payload = self._projection()
        del payload["provider_scope_projection"]["background_population_count"]
        report = validate_provider_scope_projection(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("PROVIDER_SCOPE_BACKGROUND_POPULATION_INVALID", report["failures"])

    def test_unbound_below_background_is_invalid(self):
        report = validate_provider_scope_projection(
            self._projection(background_population_count=3, unbound_visible_living_entity_count=1)
        )
        self.assertIn("PROVIDER_SCOPE_UNBOUND_BELOW_BACKGROUND", report["failures"])

    def test_instance_count_zero_is_invalid(self):
        report = validate_provider_scope_projection(
            self._projection(visible_entity_instance_counts={"CHAR-A": 0},
                             visible_living_entity_instance_total=0)
        )
        self.assertIn(
            "PROVIDER_SCOPE_VISIBLE_INSTANCE_CARDINALITY_INVALID:CHAR-A", report["failures"]
        )


class PopulationClauseAgreementTest(unittest.TestCase):
    """6 — the renderer's sentence and the gate's expectation are one builder."""

    def test_gate_accepts_clause_built_from_declared_numbers(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-A", "canonical_name": "A"}],
            scene_domain="STREET",
            background_population_count=2,
        )
        prompt = (
            "@Image1: exclusive identity of A; render exactly one visible instance of A.\n"
            "population_scope: "
            + population_clause_core(
                1, background_population_count=2, unbound_visible_living_entity_count=2
            )
            + ".\n"
        )
        report = validate_provider_scope_projection(
            {"provider_scope_projection": projection}, prompt_text=prompt, model="MiniMax-H3"
        )
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_stale_zero_clause_is_rejected_when_two_are_declared(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-A", "canonical_name": "A"}],
            scene_domain="STREET",
            background_population_count=2,
        )
        prompt = (
            "@Image1: exclusive identity of A; render exactly one visible instance of A.\n"
            "population_scope: render exactly 1 living entity instances in total; "
            "background population count=0; unbound living entity count=0.\n"
        )
        report = validate_provider_scope_projection(
            {"provider_scope_projection": projection}, prompt_text=prompt, model="MiniMax-H3"
        )
        self.assertIn("H3_PROVIDER_SCOPE_EXCLUSIVE_POPULATION_CLAUSE_MISSING", report["failures"])

    def test_full_clause_includes_the_renderer_prefix(self):
        self.assertTrue(
            population_clause(2).startswith("Only bound identities are visible; render exactly 2")
        )


class ActiveFromEpisodeOverrideTest(unittest.TestCase):
    """7 — a below-threshold episode can opt in without moving the constant."""

    def _payload(self, **extra):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-A", "canonical_name": "A"}],
            scene_domain="STREET",
        )
        payload = {"episode": "E12", "provider_scope_projection": projection}
        payload.update(extra)
        return payload

    def test_below_threshold_is_quiet_by_default(self):
        self.assertLess(12, ACTIVE_FROM_EPISODE)
        report = validate_provider_scope_projection(
            self._payload(), prompt_text="nothing declared here", model="MiniMax-H3"
        )
        self.assertEqual(report["status"], "PASS")

    def test_declared_checks_turn_the_same_gate_on(self):
        # A prompt missing every required clause is quiet below the threshold
        # and rejected once the unit declares the checks.  Same payload, same
        # prompt, one field different — that difference is what is under test.
        bare = "@Image1: exclusive identity of A.\nno clauses here"
        self.assertEqual(
            validate_provider_scope_projection(
                self._payload(), prompt_text=bare, model="MiniMax-H3"
            )["status"],
            "PASS",
        )
        enforced = validate_provider_scope_projection(
            self._payload(provider_scope_prompt_checks="ENFORCED"),
            prompt_text=bare,
            model="MiniMax-H3",
        )
        self.assertEqual(enforced["status"], "FAIL")
        self.assertIn(
            "H3_PROVIDER_SCOPE_EXCLUSIVE_POPULATION_CLAUSE_MISSING", enforced["failures"]
        )

    def test_declared_off_keeps_an_above_threshold_episode_quiet(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[{"character_id": "CHAR-A", "canonical_name": "A"}],
            scene_domain="STREET",
        )
        report = validate_provider_scope_projection(
            {"episode": "E60", "provider_scope_projection": projection,
             "provider_scope_prompt_checks": "DISABLED"},
            prompt_text="no clauses at all",
            model="MiniMax-H3",
        )
        self.assertEqual(report["status"], "PASS")


class RendererUndeclaredPopulationTest(unittest.TestCase):
    """8 — the renderer must not invent the number it failed to receive."""

    def test_undeclared_population_is_a_hard_error_not_a_fallback(self):
        # The renderer reads the total from the projection.  Previously a
        # missing field silently became len(scope_bindings), which turned an
        # undeclared population into a plausible-looking number.  Assert the
        # raise exists at the source, since reaching it through render_h3_prompt
        # requires a fully valid English contract first.
        import inspect

        source = inspect.getsource(render_h3_prompt)
        self.assertIn("H3_PROVIDER_SCOPE_POPULATION_UNDECLARED", source)
        self.assertNotIn(
            "or len(scope_bindings)", source,
            "the population total must not fall back to the binding count",
        )


class AnonymousRoleTierTest(unittest.TestCase):
    """9 — a walk-on has somewhere to live other than the forbidden list."""

    def test_anonymous_role_leaves_the_forbidden_list(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-INNKEEPER"],
            visible_prop_ids=[],
            episode_character_catalog=[
                {"character_id": "CHAR-INNKEEPER", "canonical_name": "店小二",
                 "identity_tier": "ANONYMOUS_FUNCTIONAL"},
                {"character_id": "CHAR-ABSENT", "canonical_name": "缺席者"},
            ],
            scene_domain="INN",
        )
        absent_ids = {row["entity_id"] for row in projection["absent_episode_entities"]}
        self.assertNotIn("CHAR-INNKEEPER", absent_ids)
        self.assertIn("CHAR-ABSENT", absent_ids)
        self.assertIn("店小二", projection["anonymous_role_descriptors"])

    def test_named_role_is_untouched_by_the_tier(self):
        projection = build_provider_scope_projection(
            visible_character_ids=["CHAR-A"],
            visible_prop_ids=[],
            episode_character_catalog=[
                {"character_id": "CHAR-A", "canonical_name": "A", "identity_tier": "NAMED"},
            ],
            scene_domain="ROOM",
        )
        self.assertEqual(projection["anonymous_role_descriptors"], [])


class ReferenceSemanticsPrecheckTest(unittest.TestCase):
    """10 — swapped reference slots and shared face plates must fail precheck."""

    def _task(self, bindings):
        return {
            "task_key": "T1",
            "prompt_contract": {
                "visible_characters": ["CHAR-A"],
                "canonical_props": [],
            },
            "canonical_characters": ["CHAR-A"],
            "canonical_props": [],
            "reference_bindings": bindings,
        }

    def test_character_plate_declared_as_scene_fails(self):
        report = precheck_submission_inputs(
            self._task([{"entity_id": "CHAR-A", "role": "SCENE", "path": "a.png"}]),
            enforce=True,
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("REFERENCE_ROLE_SEMANTICS_INVALID", report["failures"])
        self.assertIn(
            "REFERENCE_ROLE_NAMESPACE_CONFLICT:CHAR-A",
            report["reference_role_semantics_failures"],
        )

    def test_prop_plate_labelled_as_identity_role_fails(self):
        report = precheck_submission_inputs(
            self._task([{"entity_id": "PROP-DEER", "role": "CHARACTER", "path": "d.png"}]),
            enforce=True,
        )
        self.assertIn(
            "REFERENCE_IDENTITY_ROLE_NOT_A_CHARACTER:PROP-DEER",
            report["reference_role_semantics_failures"],
        )

    def test_two_identities_sharing_one_plate_fails(self):
        report = precheck_submission_inputs(
            self._task([
                {"entity_id": "CHAR-A", "role": "IDENTITY", "path": "same.png"},
                {"entity_id": "CHAR-B", "role": "IDENTITY", "path": "same.png"},
            ]),
            enforce=True,
        )
        self.assertTrue(
            any(item.startswith("REFERENCE_IDENTITY_PLATE_SHARED_BY:")
                for item in report["reference_role_semantics_failures"])
        )

    def test_consistent_bindings_pass_the_semantics_check(self):
        report = precheck_submission_inputs(
            self._task([{"entity_id": "CHAR-A", "role": "IDENTITY", "path": "a.png"}]),
            enforce=False,
        )
        self.assertEqual(report["reference_role_semantics_failures"], [])


class CauseConfidenceTest(unittest.TestCase):
    """11 — a determinate finding must be distinguishable from an inferred one."""

    def test_missing_anchor_is_determinate(self):
        report = precheck_submission_inputs(
            {
                "task_key": "T1",
                "canonical_characters": ["CHAR-A"],
                "canonical_props": [],
                "prompt_contract": {"visible_characters": ["CHAR-A"]},
                "reference_bindings": [],
            },
            enforce=True,
        )
        self.assertEqual(report["cause_confidence"], "DETERMINATE")

    def test_clean_input_reports_not_applicable(self):
        report = precheck_submission_inputs(
            {
                "task_key": "T1",
                "canonical_characters": [],
                "canonical_props": [],
                "prompt_contract": {"visible_characters": []},
                "reference_bindings": [],
            },
            enforce=False,
        )
        self.assertEqual(report["cause_confidence"], "NOT_APPLICABLE")


class RerollLedgerWriterTest(unittest.TestCase):
    """12 — the ledger the guard reads must have a writer next to its reader."""

    def test_first_request_is_number_one_and_second_is_two(self):
        ledger = {}
        self.assertEqual(reroll_number_for(ledger, "U1"), 1)
        record_reroll_event(
            ledger, shot_id="U1", reroll_number=1, failure_reason="FREEZE",
            outcome="SUBMITTED", recorded_at="2026-10-16T00:00:00Z",
        )
        self.assertEqual(reroll_number_for(ledger, "U1"), 2)

    def test_requested_outcome_does_not_consume_the_episode_budget(self):
        ledger = {}
        record_reroll_event(
            ledger, shot_id="U1", reroll_number=1, failure_reason="FREEZE",
            outcome="REQUESTED", recorded_at="2026-10-16T00:00:00Z",
        )
        # A request that was never submitted must not advance the ordinal.
        self.assertEqual(reroll_number_for(ledger, "U1"), 1)

    def test_ordinal_is_tracked_per_shot(self):
        ledger = {}
        for shot in ("U1", "U1", "U2"):
            record_reroll_event(
                ledger, shot_id=shot, reroll_number=1, failure_reason="FREEZE",
                outcome="SUBMITTED", recorded_at="2026-10-16T00:00:00Z",
            )
        self.assertEqual(reroll_number_for(ledger, "U1"), 3)
        self.assertEqual(reroll_number_for(ledger, "U2"), 2)

    def test_event_is_findable_by_the_guard_fields(self):
        ledger = {}
        record_reroll_event(
            ledger, shot_id="U1", reroll_number=1, failure_reason="FREEZE",
            failure_class="FREEZE", outcome="COMPLETED", recorded_at="2026-10-16T00:00:00Z",
            net_charged_credits=20,
        )
        event = ledger["events"][0]
        for key in ("shot_id", "outcome", "failure_class", "failure_reason"):
            self.assertIn(key, event)
        self.assertEqual(event["net_charged_credits"], 20)


class PolicyKeysReadTest(unittest.TestCase):
    """13 — policy keys that exist must actually be read."""

    POLICY = {
        "max_rerolls_per_shot": 2,
        "episode_reroll_shot_fraction": 0.15,
        "same_reason_distinct_shot_limit": 2,
        "advise_margin_fraction": 0.1,
        "block_failure_classes": ["FREEZE", "BURNED_IN_TEXT"],
    }

    def test_block_failure_class_is_reported(self):
        from tools.reroll_cost_guard import evaluate

        result = evaluate(
            self.POLICY, {"events": []}, shot_id="U1", reroll_number=1,
            failure_tier="BLOCK", failure_reason="FREEZE", total_paid_tasks=20,
            failure_class="FREEZE",
        )
        self.assertTrue(result["policy_blocks_this_failure_class"])
        self.assertIn("FREEZE", result["policy_block_failure_classes"])

    def test_block_class_at_advise_tier_is_rejected(self):
        from tools.reroll_cost_guard import evaluate

        result = evaluate(
            self.POLICY, {"events": []}, shot_id="U1", reroll_number=1,
            failure_tier="ADVISE", failure_reason="FREEZE", total_paid_tasks=20,
            failure_class="FREEZE",
        )
        self.assertIn("POLICY_BLOCK_CLASS_REQUIRES_BLOCK_TIER", result["failures"])

    def test_margin_fraction_is_reported(self):
        from tools.reroll_cost_guard import evaluate

        result = evaluate(
            self.POLICY, {"events": []}, shot_id="U1", reroll_number=1,
            failure_tier="BLOCK", failure_reason="FREEZE", total_paid_tasks=20,
        )
        self.assertIn("episode_budget_headroom_ratio", result)


class SubmissionGateReachabilityTest(unittest.TestCase):
    """14 — the repo entrypoint must run every gate the deployed one runs."""

    def test_shared_gate_chain_reports_the_missing_anchor(self):
        failures = validate_task_submission_gates({
            "task_key": "U1",
            "media_type": "VIDEO",
            "retry_attempt": 1,
            "canonical_characters": ["CHAR-A"],
            "canonical_props": [],
            "prompt_contract": {"visible_characters": ["CHAR-A"]},
            "reference_bindings": [],
        })
        self.assertTrue(
            any("INPUT_COMPLETENESS_FAILED" in value for value in failures), failures
        )

    def test_repo_main_calls_the_shared_gate_chain(self):
        import ast
        from pathlib import Path

        source = Path("tools/submit_giggle_video_manifest_v2.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        main_node = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        called = {
            node.func.id for node in ast.walk(main_node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("validate_task_submission_gates", called)

    def test_retry_change_rejects_undeclared_stochastic_change(self):
        report = validate_retry_change({
            "failure_attribution": "MODEL_STOCHASTIC",
            "changed_variables": ["PROMPT"],
        })
        self.assertIn("RETRY_CHANGED_WRONG_VARIABLE", report["failures"])

    def test_retry_cap_requires_redesign_after_a_content_failure(self):
        failures = validate_submission_attempt({
            "retry_attempt": 2,
            "media_type": "VIDEO",
            "prompt_sha256": "a" * 64,
            "prior_prompt_sha256": ["b" * 64],
            "failure_memory": ["FREEZE"],
            "material_change_from_prior_attempt": "rebuilt",
        })
        self.assertIn("VIDEO_CONTENT_RETRY_REQUIRES_EXECUTION_PROMPT_REDESIGN", failures)


if __name__ == "__main__":
    unittest.main()
