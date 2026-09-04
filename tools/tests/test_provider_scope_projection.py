import unittest

from provider_scope_projection import build_provider_scope_projection, validate_provider_scope_projection


class ProviderScopeProjectionTests(unittest.TestCase):
    def _projection(self):
        return build_provider_scope_projection(
            visible_character_ids=["CHAR-BAILI"],
            visible_prop_ids=[],
            episode_character_catalog=[
                {"character_id": "CHAR-BAILI", "canonical_name": "白鲤", "provider_entity_label": "Princess Baili"},
                {"character_id": "CHAR-CROW", "canonical_name": "乌鸦", "provider_entity_label": "the black crow"},
                {"character_id": "CHAR-SOLDIER", "canonical_name": "军士", "provider_entity_label": "soldier"},
            ],
            reference_images=[{"entity_id": "CHAR-BAILI", "provider_entity_label": "Princess Baili"}],
            scene_domain="REALITY_NORTHERN_SONG",
        )

    def test_h3_explicit_reference_mapping_passes(self):
        task = {"model": "MiniMax-H3", "provider_scope_projection": self._projection()}
        prompt = "@Image1: exclusive identity of Princess Baili; render exactly one visible instance of Princess Baili.\nsummary: Princess Baili looks over a wall.\nnegative_constraints: no extras."
        self.assertEqual(validate_provider_scope_projection(task, prompt_text=prompt, model="MiniMax-H3")["status"], "PASS")

    def test_absent_episode_entity_in_positive_prompt_fails(self):
        task = {"model": "MiniMax-H3", "provider_scope_projection": self._projection()}
        prompt = "@Image1: exclusive identity of Princess Baili; render exactly one visible instance of Princess Baili.\nsummary: Princess Baili and the black crow look over a wall."
        report = validate_provider_scope_projection(task, prompt_text=prompt, model="MiniMax-H3")
        self.assertIn("PROVIDER_SCOPE_ABSENT_ENTITY_IN_POSITIVE_PROMPT:CHAR-CROW:the black crow", report["failures"])

    def test_h3_negative_clause_may_not_name_absent_entity(self):
        task = {"model": "MiniMax-H3", "provider_scope_projection": self._projection()}
        prompt = "@Image1: exclusive identity of Princess Baili; render exactly one visible instance of Princess Baili.\nsummary: Princess Baili looks over a wall.\nnegative_constraints: no soldier or black crow."
        self.assertEqual(validate_provider_scope_projection(task, prompt_text=prompt, model="MiniMax-H3")["status"], "FAIL")

    def test_h3_visible_entity_cardinality_is_required(self):
        task = {"model": "MiniMax-H3", "provider_scope_projection": self._projection()}
        prompt = "@Image1: exclusive identity of Princess Baili.\nsummary: Princess Baili looks over a wall."
        report = validate_provider_scope_projection(task, prompt_text=prompt, model="MiniMax-H3")
        self.assertIn("H3_PROVIDER_SCOPE_INSTANCE_CARDINALITY_MISSING:CHAR-BAILI", report["failures"])

    def test_sd2_negative_only_absent_term_remains_allowed(self):
        task = {"model": "seedance-2.0-pro", "provider_scope_projection": self._projection()}
        prompt = "summary: Princess Baili looks over a wall.\nnegative_constraints: no soldier or black crow."
        self.assertEqual(validate_provider_scope_projection(task, prompt_text=prompt, model="seedance-2.0-pro")["status"], "PASS")

    def test_reference_binding_must_be_exclusive(self):
        projection = self._projection()
        projection["reference_identity_bindings"][0]["exclusive_identity_owner"] = False
        report = validate_provider_scope_projection({"provider_scope_projection": projection})
        self.assertIn("PROVIDER_SCOPE_REFERENCE_OWNER_NOT_EXCLUSIVE:CHAR-BAILI", report["failures"])

    def test_e56_provider_prompt_fails_closed_without_projection(self):
        report = validate_provider_scope_projection(
            {"episode": "E56", "model": "MiniMax-H3"},
            prompt_text="summary: a current-unit subject moves.", model="MiniMax-H3",
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("PROVIDER_SCOPE_PROJECTION_MISSING", report["failures"])

    def test_legacy_episode_without_projection_remains_compatible(self):
        report = validate_provider_scope_projection(
            {"episode": "E55", "model": "seedance-2.0-pro"},
            prompt_text="【任务】旧版兼容", model="seedance-2.0-pro",
        )
        self.assertEqual(report["status"], "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
