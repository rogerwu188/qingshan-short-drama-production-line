# Port parity report — lines/nalu/runtime/tools vs the production instance

Generated offline by diffing each ported file against the deployment copy. `changed_lines` counts added lines;
PATH_ONLY means every changed line is a path substitution (`_np.*`), the three-line `nalu_paths` prelude, or a
docstring path rewritten to `$ENGINE_ROOT` / `$RUNTIME_ROOT`.

| file | class | changed_lines |
|---|---|---|
| action_role_evidence_writer.py | PATH_ONLY | 0 |
| bootstrap_identity_cards.py | PATH_ONLY | 4 |
| bootstrap_voice_references.py | PATH_ONLY | 5 |
| build_burnin_subtitles.py | PATH_ONLY | 0 |
| build_e01_layers.py | PATH_ONLY | 6 |
| build_e02_layers.py | PATH_ONLY | 5 |
| build_e03_layers.py | PATH_ONLY | 5 |
| build_episode_asset_requirements.py | PATH_ONLY | 10 |
| build_keyframe_manifest.py | PATH_ONLY | 4 |
| build_nalu_preproduction.py | PATH_ONLY | 5 |
| extend_global_space_map.py | PATH_ONLY | 8 |
| final_qa_evidence_bundle.py | PATH_ONLY | 0 |
| generate_period_look.py | PATH_ONLY | 7 |
| identity_qa_lock.py | PATH_ONLY | 5 |
| ingest_yewujiang_source.py | PATH_ONLY | 5 |
| keyframe_q1_builder.py | PATH_ONLY | 0 |
| library_lock_non_plate.py | PATH_ONLY | 5 |
| materialize_paid_authorization.py | PATH_ONLY | 5 |
| nalu_budget_ledger.py | PATH_ONLY | 5 |
| nalu_paths.py | NEW | 0 |
| nalu_pipeline.py | PATH_ONLY | 7 |
| nalu_prompt_rules.py | PATH_ONLY | 0 |
| nalu_qa_common.py | PATH_ONLY | 5 |
| nalu_selective_bgm.py | PATH_ONLY | 4 |
| post_generation_qa_runner.py | PATH_ONLY | 0 |
| prompt_batch_finalize.py | PATH_ONLY | 4 |
| prompt_batch_qa.py | PATH_ONLY | 5 |
| prompt_batch_register.py | PATH_ONLY | 4 |
| review_fill/asr_units.py | PATH_ONLY | 0 |
| review_fill/contact_sheet.py | PATH_ONLY | 0 |
| review_fill/e02_fill_action_role_answers.py | PATH_ONLY | 5 |
| review_fill/e02_fill_identity_answers.py | PATH_ONLY | 5 |
| review_fill/e02_fill_keyframe_answers.py | PATH_ONLY | 5 |
| review_fill/e02_fill_post_gen_plot.py | PATH_ONLY | 5 |
| review_fill/e02_fill_start_frame_answers.py | PATH_ONLY | 5 |
| review_fill/e02_fill_video_q2.py | PATH_ONLY | 5 |
| review_fill/e03_fill_action_role_answers.py | PATH_ONLY | 5 |
| review_fill/e03_fill_identity_answers.py | PATH_ONLY | 5 |
| review_fill/e03_fill_keyframe_answers.py | PATH_ONLY | 5 |
| review_fill/e03_fill_post_gen_plot.py | PATH_ONLY | 5 |
| review_fill/e03_fill_start_frame_answers.py | PATH_ONLY | 5 |
| review_fill/e03_fill_video_q2.py | PATH_ONLY | 5 |
| review_fill/video_sheets.py | PATH_ONLY | 0 |
| start_frame_evidence_writer.py | PATH_ONLY | 0 |
| static_design_gate.py | PATH_ONLY | 0 |
| video_q2_builder.py | PATH_ONLY | 5 |
| vlm_review_protocol.py | PATH_ONLY | 4 |
