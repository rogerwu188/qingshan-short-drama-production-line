# Runtime state templates (structure only)

These are the files the nalu tools read or write under `$NALU_RUNTIME_ROOT/runtime/`. Values are blank; row shapes
are defined by the tool that writes them (named per file). `bootstrap_runtime_root.py` copies them into a fresh
runtime root without the `.TEMPLATE` suffix. Nothing here carries provider ids, media hashes or real people.

| template | installed as | written by | read by |
|---|---|---|---|
| asset_library | runtime/asset_library.json | S3 identity_qa_lock lock, library_lock_non_plate, engine initial_asset_library | every later episode (SHA reuse), build_nalu_preproduction |
| nalu_character_asset_registry | runtime/nalu_character_asset_registry.json | identity_qa_lock registry (rebuilt after each lock) | keyframe_q1_builder, video_q2_builder (identity cosine) |
| nalu_entity_registry | runtime/nalu_entity_registry.json | hand-maintained per work (additive) | engine binding guard via QINGSHAN_ENTITY_REGISTRY |
| character_source_map | runtime/character_source_map.json | tools/intake_character_sources.py (repo root) | bootstrap_identity_cards, generate_period_look |
| episode_source_map | runtime/episode_source_map.json | ingest tooling / hand | build_e0N_layers (chapter → episode) |
| voice_catalog | runtime/voice_catalog.json | agent, after `agentcut speech-voices` | S4 bootstrap_voice_references |
| voice_registry | runtime/voice_registry.json | S4 bootstrap_voice_references | engine via QINGSHAN_VOICE_REGISTRY |
| agentcut_character_voice_reference_policy | runtime/agentcut_character_voice_reference_policy.json | S4 | AgentCut via QINGSHAN_AGENTCUT_VOICE_POLICY |
| budget_ledger | runtime/budget/ledger.json | nalu_budget_ledger.py (snapshots) | every paid stage (cap guard) |
| reroll_cost_guard_policy | runtime/configs/reroll_cost_guard_policy_<EP>_seq<N>.json | line owner order | S6 loop script (REQUIRE_GUARD) |
