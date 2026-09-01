# Provider prompt compiler test migration map

This map records the migration from the legacy prompt-dump serializers to the
shared execution IR plus model-native renderers. A removed string assertion is
not a removed requirement: every row below names its replacement assertion.

| Legacy assertion/test | Requirement it encoded | Replacement assertion | Location |
|---|---|---|---|
| `test_router_keeps_seedance_on_unchanged_compiler` mocked the old function | SD2 and H3 must remain independent renderer routes | SD2 output contains `【时间轴】` and not H3 grammar | `test_video_prompt_compiler.py::test_router_keeps_seedance_grammar_independent` |
| `test_h3_dialogue_is_the_only_speakable_text` | Only authorized dialogue may be spoken | CJK outside `<d>` is zero; the literal occurs once; vocal rule is present | `test_h3_dialogue_is_the_only_cjk_outside_machine_metadata` |
| `test_h3_dialogue_fails_closed_without_speaker_voice_contract` | Every spoken line has a registered speaker voice | Missing voice contract raises `SPEAKER_VOICE_CONTRACT` | same test name in migrated suite |
| `test_h3_silent_unit_explicitly_closes_mouths` | Silent clips cannot invent speech | No `<d>` tag and all mouths remain closed | same test name in migrated suite |
| `test_h3_contact_action_binds_limb_ownership_and_occlusion_topology` | Prevent isolated/owner-swapped/malformed limbs | Provider prompt contains continuous shoulder-to-finger ownership and malformed-limb bans | same test name in migrated suite |
| `test_h3_combat_uses_real_motion_contract_not_reference_tableaux` | Combat must be a force chain, not a pose slideshow | Provider prompt contains setup/contact/feedback/new-position chain and bans posing/push-hands/interpolation | same test name in migrated suite |
| `test_h3_transition_contract_is_serialized_as_semantics_not_ids` | Transitions preserve state without leaking IDs | English transition semantics appear; internal boundary IDs do not | same test name in migrated suite |
| `test_h3_internal_transition_rows_bind_in_exact_shot_order` | Internal bridges bind between the correct beats | Text index asserts beat 1 < bridge < beat 2 | same test name in migrated suite |
| `test_h3_validator_rejects_seedance_grammar_and_unisolated_dialogue` | H3 cannot accept SD2 grammar or untagged dialogue | Required H3 sections plus English/CJK boundary and exact d-tag validation | `test_h3_dialogue_is_the_only_cjk_outside_machine_metadata`; `test_h3_cjk_and_quoted_cjk_hard_checks` |
| `test_h3_strips_speakable_action_scaffolding` | Chinese editorial scaffolding must not become speech | English translation boundary excludes the Chinese source marker and dialogue occurs once | `test_h3_strips_speakable_action_scaffolding_by_translation_boundary` |
| `test_h3_validator_rejects_speakable_meta_outside_dialogue` | Machine metadata cannot be vocalized | Any CJK outside d-tags is a compile failure | `test_h3_cjk_and_quoted_cjk_hard_checks` |
| `test_h3_speech_isolation_repair_profile_is_terse_and_dialogue_bounded` | Speech repair retains exact dialogue isolation | Profile-specific constraint remains and shared d-tag/CJK gates still run | `test_h3_profiles_preserve_existing_safety_constraints` |
| `test_h3_minimal_audio_rescue_has_one_literal_dialogue_and_tiny_surface` | Audio rescue cannot broaden visual/speech scope | Profile-specific native-sound-only rule plus single tagged literal and compact prompt budget | `test_h3_profiles_preserve_existing_safety_constraints`; `test_model_prompt_is_compact_and_does_not_leak_machine_contract` |
| `test_h3_all_profiles_fail_closed_without_zero_text_frame_contract` | Every H3 profile must forbid burned text | Removing `TEXT-FREE FRAME` fails required-section validation | `test_h3_zero_text_frame_contract_is_fail_closed` |
| `test_h3_adult_female_visual_is_explicitly_adult_and_model_specific` | Adult styling is H3-only and age-gated | H3 emits tasteful adult styling; SD2 does not | same test name in migrated suite |
| `test_h3_adult_female_visual_rejects_explicit_direction` | Explicit sexual/nude instructions fail closed | Established validator still raises the explicit-content code | same test name in migrated suite |
| `test_model_prompt_is_compact_and_does_not_leak_machine_contract` | Provider prompt cannot dump schemas, IDs, or SHA receipts | Prompt length bound and forbidden machine-token assertions; semantic coverage receipt PASS | same test name in both migrated suites |
| Legacy identical-string state evidence | A real state change must exist | Typed `entry_code`/`exit_code` are required and must differ | `test_shared_video_execution_compiler.py`; `sd2_motion_density_gate.py` |
| Upstream `execution_semantics_sha256` equality | Both renderers must cover the same shared facts | Each renderer independently proves rendered clause coverage; required fact-set hashes must match | `test_shared_video_execution_compiler.py::test_sd2_and_h3_share_execution_semantics_but_not_prompt_grammar` |
| No legacy sequence test | Combat scene must have duration contrast | 5+ combat run requires two durations, one 7s+ exchange, and max four identical durations | `test_video_sequence_rhythm_gate.py` |

Deletion policy: any future removal of a requirement-bearing assertion must add
or update a row in this file in the same change. CI enforces the frozen
replacement registry in `test_prompt_test_migration_map.py`; an intentional
migration must update both the registry and this table in the same reviewed
change.

Additional registered replacement tests used by that CI gate:

- `test_h3_cjk_and_quoted_cjk_hard_checks`
- `test_h3_zero_text_frame_contract_is_fail_closed`
- `test_identical_entry_and_exit_fails_closed`
- `test_combat_impulse_gates_are_deterministic`
- `test_five_identical_short_combat_units_fail`
- `test_contrast_and_exchange_pass`
- `test_named_director_override_is_auditable`
- `test_absolute_score_is_advisory_until_calibrated`
- `test_ab_requires_1_8x_improvement_and_cut_is_excluded`
