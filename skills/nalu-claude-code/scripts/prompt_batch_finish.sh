#!/bin/bash
# Whole-batch prompt gate, after the reviewer's answers exist: receipts -> register (must print PASS).
set -eo pipefail
EP=${1:-E01}; E=${NALU_ENGINE_ROOT:?}
cd $E; export NALU_WORK_ROOT=$E/workflow/nalu
# The prompt QA tools judge voice-over by the CURRENT_PORTABLE policy (voice_over_narration.enabled()); without it a
# narration-only shot is checked as on-screen dialogue and fails vp_dialogue_verbatim (field device …1324 E03,
# 2026-11-08).  Set it per QA call only -- never in this shell, where nalu_pipeline S1 would demand a private project.json.
QA_ENV="env -u GIGGLE_API_KEY NALU_POLICY_PROFILE=CURRENT_PORTABLE"
REP=$E/workflow/nalu/$EP/preproduction/reports
$QA_ENV $E/.qingshan-venv/bin/python lines/nalu/runtime/tools/prompt_batch_qa.py receipts --episode $EP --digest $REP/${EP}_PROMPT_BATCH_DIGEST.json --answers $REP/${EP}_PROMPT_BATCH_ANSWERS.json --out-dir $REP/prompt_batch_qa | tail -1
$QA_ENV $E/.qingshan-venv/bin/python lines/nalu/runtime/tools/prompt_batch_register.py --episode $EP --execution-id $EP-PROMPT-BATCH-V1 --qa-dir $REP/prompt_batch_qa --report $REP/${EP}_PROMPT_BATCH_REGISTER.json | tail -1
